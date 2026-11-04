import asyncio

import httpx
import respx

from square_mcp.__main__ import _build_http_app
from square_mcp.config import Settings
from square_mcp.server import create_mcp_server

from .conftest import lifespan_running

PROD_BASE = "https://connect.squareup.com/v2"
MCP_HEADERS = {"Accept": "application/json, text/event-stream"}


def _make_app():
    settings = Settings(auth_mode="gateway")
    mcp = create_mcp_server(settings)
    return _build_http_app(mcp, settings)


async def test_missing_access_token_returns_401_on_mcp_endpoint():
    """TC2 (AC2): no X-Square-Access-Token -> 401, required_headers lists it, no outbound call."""
    app = _make_app()
    with respx.mock(assert_all_mocked=True) as mock:
        async with lifespan_running(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
                resp = await http.post(
                    "/mcp",
                    json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                    headers=MCP_HEADERS,
                )
        assert mock.calls.call_count == 0  # zero outbound Square calls

    assert resp.status_code == 401
    body = resp.json()
    assert body["required_headers"] == ["X-Square-Access-Token"]


async def test_health_check_does_not_require_square_credential():
    """TC6 (AC6): GET /health returns 200 with no Square credential configured anywhere."""
    app = _make_app()
    async with lifespan_running(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
            resp = await http.get("/health")

    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_tools_list_succeeds_without_prior_initialize_session():
    """TC7 (AC7): tools/list with no prior initialize session succeeds with 200 (stateless)."""
    app = _make_app()
    async with lifespan_running(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
            resp = await http.post(
                "/mcp",
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                headers={**MCP_HEADERS, "X-Square-Access-Token": "tenant-token"},
            )

    assert resp.status_code == 200


async def test_concurrent_calls_do_not_leak_credentials_across_tenants():
    """TC5 (AC5): two concurrent calls each resolve a client with only their own token/env."""
    app = _make_app()

    async def call_tool(http: httpx.AsyncClient, location_id: str, token: str, environment: str):
        body = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "square_get_inventory_count",
                "arguments": {"catalog_object_id": location_id},
            },
        }
        headers = {**MCP_HEADERS, "X-Square-Access-Token": token}
        if environment:
            headers["X-Square-Environment"] = environment
        return await http.post("/mcp", json=body, headers=headers)

    async with lifespan_running(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
            with respx.mock(assert_all_called=False) as mock:
                mock.get("https://connect.squareup.com/v2/inventory/obj-a").mock(
                    return_value=httpx.Response(200, json={"counts": []})
                )
                mock.get("https://connect.squareupsandbox.com/v2/inventory/obj-b").mock(
                    return_value=httpx.Response(200, json={"counts": []})
                )

                resp_a, resp_b = await asyncio.gather(
                    call_tool(http, "obj-a", "tenant-a-token", ""),
                    call_tool(http, "obj-b", "tenant-b-token", "sandbox"),
                )

                assert resp_a.status_code == 200
                assert resp_b.status_code == 200

                calls_by_path = {
                    (call.request.url.host, call.request.url.path): call.request.headers.get(
                        "authorization"
                    )
                    for call in mock.calls
                }

    assert calls_by_path[("connect.squareup.com", "/v2/inventory/obj-a")] == "Bearer tenant-a-token"
    assert (
        calls_by_path[("connect.squareupsandbox.com", "/v2/inventory/obj-b")]
        == "Bearer tenant-b-token"
    )
