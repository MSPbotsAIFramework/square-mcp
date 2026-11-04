import httpx
import pytest
import respx

from square_mcp.api_client import SquareClient, SquareError

PROD_BASE = "https://connect.squareup.com/v2"
SANDBOX_BASE = "https://connect.squareupsandbox.com/v2"


async def test_access_token_forwarded_as_bearer_auth():
    """TC1 (AC1): outbound request carries Authorization: Bearer <token>."""
    client = SquareClient("tenant-token", base_url=PROD_BASE)
    with respx.mock(assert_all_called=True) as mock:
        route = mock.get(f"{PROD_BASE}/locations").mock(
            return_value=httpx.Response(200, json={"locations": []})
        )
        await client.get("/locations")
    assert route.calls.last.request.headers["authorization"] == "Bearer tenant-token"
    assert route.calls.last.request.headers["square-version"] == "2024-07-17"


async def test_environment_header_selects_base_url():
    """TC3 (AC3): the resolved base_url is sandbox vs production."""
    prod_client = SquareClient("t", base_url=PROD_BASE)
    sandbox_client = SquareClient("t", base_url=SANDBOX_BASE)

    with respx.mock(assert_all_called=True) as mock:
        prod_route = mock.get(f"{PROD_BASE}/locations").mock(
            return_value=httpx.Response(200, json={"locations": []})
        )
        sandbox_route = mock.get(f"{SANDBOX_BASE}/locations").mock(
            return_value=httpx.Response(200, json={"locations": []})
        )
        await prod_client.get("/locations")
        await sandbox_client.get("/locations")

    assert prod_route.called
    assert sandbox_route.called


async def test_4xx_maps_to_expected_error_code():
    """TC23 (AC23), 4xx half: a 404 maps to not_found, a 400 to invalid_argument."""
    client = SquareClient("t", base_url=PROD_BASE)

    with respx.mock(assert_all_called=True) as mock:
        mock.get(f"{PROD_BASE}/customers/missing").mock(
            return_value=httpx.Response(
                404,
                json={
                    "errors": [
                        {
                            "category": "INVALID_REQUEST_ERROR",
                            "code": "NOT_FOUND",
                            "detail": "no such customer",
                        }
                    ]
                },
            )
        )
        with pytest.raises(SquareError) as exc_info:
            await client.get("/customers/missing")

    assert exc_info.value.code == "not_found"
    assert exc_info.value.status_code == 404
    assert exc_info.value.retryable is False

    with respx.mock(assert_all_called=True) as mock:
        mock.get(f"{PROD_BASE}/bad").mock(
            return_value=httpx.Response(
                400,
                json={
                    "errors": [
                        {
                            "category": "INVALID_REQUEST_ERROR",
                            "code": "BAD_REQUEST",
                            "detail": "bad",
                        }
                    ]
                },
            )
        )
        with pytest.raises(SquareError) as exc_info:
            await client.get("/bad")

    assert exc_info.value.code == "invalid_argument"
    assert exc_info.value.retryable is False


async def test_5xx_maps_to_upstream_error():
    """TC23 (AC23), 5xx half: a 503 exhausts retries then maps to upstream_error."""
    client = SquareClient("t", base_url=PROD_BASE)

    with respx.mock(assert_all_called=True) as mock:
        route = mock.get(f"{PROD_BASE}/locations").mock(
            return_value=httpx.Response(
                503, json={"errors": [{"detail": "down"}]}, headers={"Retry-After": "0"}
            )
        )
        with pytest.raises(SquareError) as exc_info:
            await client.get("/locations")

    assert exc_info.value.code == "upstream_error"
    assert exc_info.value.retryable is True
    # one initial attempt + retries up to the configured cap
    assert route.call_count >= 1


async def test_429_retries_honoring_retry_after_then_gives_up():
    """TC23 (AC23): a 429 that never clears retries (Retry-After) then raises rate_limited."""
    client = SquareClient("t", base_url=PROD_BASE)

    with respx.mock(assert_all_called=True) as mock:
        route = mock.get(f"{PROD_BASE}/locations").mock(
            return_value=httpx.Response(
                429, json={"errors": [{"detail": "slow down"}]}, headers={"Retry-After": "0"}
            )
        )
        with pytest.raises(SquareError) as exc_info:
            await client.get("/locations")

    assert exc_info.value.code == "rate_limited"
    assert exc_info.value.retryable is True
    # initial attempt + 3 retries (the configured _MAX_RETRY_ATTEMPTS)
    assert route.call_count == 4


async def test_429_succeeds_after_one_retry():
    """A 429 followed by a 200 returns the successful result without raising."""
    client = SquareClient("t", base_url=PROD_BASE)

    with respx.mock(assert_all_called=True) as mock:
        route = mock.get(f"{PROD_BASE}/locations")
        route.side_effect = [
            httpx.Response(
                429, json={"errors": [{"detail": "slow down"}]}, headers={"Retry-After": "0"}
            ),
            httpx.Response(200, json={"locations": [{"id": "loc_1"}]}),
        ]
        result = await client.get("/locations")

    assert result == {"locations": [{"id": "loc_1"}]}
    assert route.call_count == 2


async def test_post_is_never_retried_on_5xx():
    """POST (e.g. refund) is not auto-retried — only safe via the caller's own idempotency key."""
    client = SquareClient("t", base_url=PROD_BASE)

    with respx.mock(assert_all_called=True) as mock:
        route = mock.post(f"{PROD_BASE}/refunds").mock(
            return_value=httpx.Response(503, json={"errors": [{"detail": "down"}]})
        )
        with pytest.raises(SquareError) as exc_info:
            await client.post(
                "/refunds", json_body={"payment_id": "pay_1"}, idempotency_key="key-1"
            )

    assert exc_info.value.code == "upstream_error"
    assert route.call_count == 1


async def test_post_merges_idempotency_key_into_body():
    client = SquareClient("t", base_url=PROD_BASE)

    with respx.mock(assert_all_called=True) as mock:
        route = mock.post(f"{PROD_BASE}/refunds").mock(
            return_value=httpx.Response(200, json={"refund": {"id": "rfnd_1"}})
        )
        await client.post("/refunds", json_body={"payment_id": "pay_1"}, idempotency_key="key-1")

    sent_body = route.calls.last.request.content
    import json as _json

    assert _json.loads(sent_body) == {"payment_id": "pay_1", "idempotency_key": "key-1"}
