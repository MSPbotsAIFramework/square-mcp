import json
from collections.abc import Awaitable, Callable

from ..api_client import SquareClient, SquareError

_NOT_CONFIGURED = SquareError(
    0,
    "not_configured",
    "Square credentials are not configured for this request.",
    False,
)


def dumps(payload: object) -> str:
    """Compact, token-economical JSON serialization (SOP §2.5)."""
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def error_envelope(error: SquareError) -> str:
    return dumps(
        {"error": {"code": error.code, "message": error.message, "retryable": error.retryable}}
    )


async def run_tool(
    client_factory: Callable[[], SquareClient | None],
    call: Callable[[SquareClient], Awaitable[str]],
) -> str:
    """Resolve a client for the current request and run `call`, mapping any
    SquareError (including one raised by client_factory itself, e.g. an
    invalid X-Square-Environment value, AC4) to the SOP §4 error envelope.

    Centralizing this means every tool function only expresses its own
    request/response shape, not error-handling boilerplate.
    """
    try:
        client = client_factory()
    except SquareError as e:
        return error_envelope(e)
    if client is None:
        return error_envelope(_NOT_CONFIGURED)
    try:
        return await call(client)
    except SquareError as e:
        return error_envelope(e)
