import asyncio
import time
from typing import Any

import httpx

from .config import DEFAULT_PRODUCTION_BASE_URL

DEFAULT_AUTH_HEADER = "X-Square-Access-Token"
DEFAULT_API_VERSION = "2024-07-17"

# Read-call retry policy (SOP §5): bounded attempts, backoff honoring
# Retry-After, single logical call kept well under the 120s hard cap.
_MAX_RETRY_ATTEMPTS = 3
_MAX_TOTAL_SECONDS = 100.0
_BACKOFF_BASE_SECONDS = 0.5
_BACKOFF_CAP_SECONDS = 10.0

_CONNECT_TIMEOUT = 5.0
_READ_TIMEOUT = 30.0


class SquareError(Exception):
    """A Square API failure already mapped to the SOP §4 error vocabulary."""

    def __init__(self, status_code: int, code: str, message: str, retryable: bool):
        self.status_code = status_code
        self.code = code
        self.message = message
        self.retryable = retryable
        super().__init__(f"Square API error {status_code} ({code}): {message}")


def _status_to_code(status_code: int) -> tuple[str, bool]:
    """Map an HTTP status from Square to the fixed (code, retryable) vocabulary."""
    if status_code in (401, 403):
        return "unauthorized", False
    if status_code == 404:
        return "not_found", False
    if status_code == 429:
        return "rate_limited", True
    if status_code >= 500:
        return "upstream_error", True
    # 400, 422, and any other unmapped 4xx are treated as a bad request.
    return "invalid_argument", False


def _extract_message(resp: httpx.Response) -> str:
    """Pull a human-readable message out of Square's error body shape.

    Square errors look like {"errors": [{"category", "code", "detail"}]}.
    Falls back to the raw text when the body does not match that shape.
    """
    try:
        body = resp.json()
    except Exception:
        return resp.text[:500]
    errors = body.get("errors") if isinstance(body, dict) else None
    if isinstance(errors, list) and errors:
        first = errors[0]
        detail = first.get("detail") or first.get("code") or str(first)
        return str(detail)[:500]
    return str(body)[:500]


class SquareClient:
    """Async httpx client wrapping the Square REST API.

    Accepts a raw access token and sends it as a Bearer token in the
    Authorization header on every API request. One client instance is scoped
    to a single request's token + environment (see server.get_client_from_context);
    it never reads a server-side stored credential.
    """

    def __init__(
        self,
        access_token: str,
        base_url: str = DEFAULT_PRODUCTION_BASE_URL,
        api_version: str = DEFAULT_API_VERSION,
    ):
        self._token = access_token
        self._base_url = base_url.rstrip("/")
        self._api_version = api_version

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Square-Version": self._api_version,
            "Content-Type": "application/json",
        }

    def _clean_params(self, params: dict | None) -> dict:
        if not params:
            return {}
        return {k: v for k, v in params.items() if v is not None}

    async def get(self, path: str, params: dict | None = None) -> Any:
        """GET with bounded retry-with-backoff on 429/5xx (idempotent, safe to retry)."""
        start = time.monotonic()
        attempt = 0
        while True:
            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(_READ_TIMEOUT, connect=_CONNECT_TIMEOUT)
                ) as client:
                    resp = await client.get(
                        f"{self._base_url}{path}",
                        headers=self._headers(),
                        params=self._clean_params(params),
                    )
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                raise SquareError(0, "upstream_error", str(exc), True) from exc

            if resp.status_code == 429 or resp.status_code >= 500:
                elapsed = time.monotonic() - start
                delay = self._retry_delay(resp, attempt)
                if attempt >= _MAX_RETRY_ATTEMPTS or elapsed + delay > _MAX_TOTAL_SECONDS:
                    self._raise_for_status(resp)
                await asyncio.sleep(delay)
                attempt += 1
                continue

            self._raise_for_status(resp)
            return resp.json() if resp.status_code != 204 else None

    async def post(
        self,
        path: str,
        json_body: dict | None = None,
        idempotency_key: str | None = None,
    ) -> Any:
        """POST — never auto-retried (only safe-to-retry via the caller's own idempotency key)."""
        body = self._clean_params(json_body)
        if idempotency_key is not None:
            body["idempotency_key"] = idempotency_key
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(_READ_TIMEOUT, connect=_CONNECT_TIMEOUT)
            ) as client:
                resp = await client.post(
                    f"{self._base_url}{path}",
                    headers=self._headers(),
                    json=body,
                )
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            raise SquareError(0, "upstream_error", str(exc), True) from exc

        self._raise_for_status(resp)
        return resp.json() if resp.status_code != 204 else None

    def _retry_delay(self, resp: httpx.Response, attempt: int) -> float:
        retry_after = resp.headers.get("Retry-After")
        if retry_after is not None:
            try:
                return max(0.0, float(retry_after))
            except ValueError:
                pass
        return min(_BACKOFF_BASE_SECONDS * (2**attempt), _BACKOFF_CAP_SECONDS)

    def _raise_for_status(self, resp: httpx.Response) -> None:
        if resp.status_code >= 400:
            code, retryable = _status_to_code(resp.status_code)
            raise SquareError(resp.status_code, code, _extract_message(resp), retryable)
