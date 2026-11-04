import json

import httpx
import pytest
import respx

from square_mcp.config import Settings
from square_mcp.server import _gateway_environment_var, _gateway_token_var, create_mcp_server

PROD_BASE = "https://connect.squareup.com/v2"
SANDBOX_BASE = "https://connect.squareupsandbox.com/v2"

EXPECTED_TOOL_NAMES = {
    "square_list_locations",
    "square_list_customers",
    "square_search_customers",
    "square_get_customer",
    "square_list_catalog_items",
    "square_get_catalog_item",
    "square_search_orders",
    "square_get_order",
    "square_list_payments",
    "square_get_payment",
    "square_get_inventory_count",
    "square_create_refund",
}


@pytest.fixture
def mcp():
    return create_mcp_server(Settings(auth_mode="gateway"))


async def _call(mcp, tool_name, arguments, token="tenant-token", environment=None):
    token_ctx = _gateway_token_var.set(token)
    env_ctx = _gateway_environment_var.set(environment)
    try:
        return await mcp.call_tool(tool_name, arguments)
    finally:
        _gateway_token_var.reset(token_ctx)
        _gateway_environment_var.reset(env_ctx)


def _text(result) -> str:
    content, _ = result
    return content[0].text


def _error(result) -> dict:
    return json.loads(_text(result))["error"]


async def test_tools_list_snapshot(mcp):
    tools = await mcp.list_tools()

    names = {t.name for t in tools}
    assert names == EXPECTED_TOOL_NAMES
    assert len(tools) == 12
    for tool in tools:
        assert tool.description, f"{tool.name} is missing a description"
        assert len(tool.description) <= 500, f"{tool.name} description exceeds 500 chars"

    refund_tool = next(t for t in tools if t.name == "square_create_refund")
    assert set(refund_tool.inputSchema.get("required", [])) == {"payment_id", "amount", "currency"}
    assert refund_tool.annotations.readOnlyHint is False
    assert refund_tool.annotations.destructiveHint is True
    assert refund_tool.annotations.idempotentHint is True

    read_tool = next(t for t in tools if t.name == "square_list_locations")
    assert read_tool.annotations.readOnlyHint is True


async def test_no_credentials_returns_not_configured_without_outbound_call(mcp):
    with respx.mock(assert_all_called=False) as mock:
        route = mock.get(url__regex=r".*")
        result = await _call(mcp, "square_list_locations", {}, token=None)
        assert not route.called

    error = _error(result)
    assert error["code"] == "not_configured"


async def test_invalid_environment_value_returns_invalid_argument(mcp):
    """TC4 (AC4): bad X-Square-Environment -> invalid_argument, zero outbound calls."""
    with respx.mock(assert_all_called=False) as mock:
        route = mock.get(url__regex=r".*")
        result = await _call(mcp, "square_list_locations", {}, environment="staging-does-not-exist")
        assert not route.called

    error = _error(result)
    assert error["code"] == "invalid_argument"
    assert error["retryable"] is False


# -- Locations (AC8) ----------------------------------------------------------


async def test_list_locations_returns_locations(mcp):
    with respx.mock(assert_all_called=True) as mock:
        mock.get(f"{PROD_BASE}/locations").mock(
            return_value=httpx.Response(
                200,
                json={"locations": [{"id": "loc_1", "name": "Main St", "status": "ACTIVE"}]},
            )
        )
        result = await _call(mcp, "square_list_locations", {})

    body = json.loads(_text(result))
    assert body[0]["id"] == "loc_1"
    assert body[0]["name"] == "Main St"
    assert body[0]["status"] == "ACTIVE"


# -- Customers (AC9-AC12) ------------------------------------------------------


async def test_list_customers_returns_page_and_cursor(mcp):
    with respx.mock(assert_all_called=True) as mock:
        mock.get(f"{PROD_BASE}/customers").mock(
            return_value=httpx.Response(
                200,
                json={"customers": [{"id": "cust_1"}], "cursor": "next-page-token"},
            )
        )
        result = await _call(mcp, "square_list_customers", {})

    body = json.loads(_text(result))
    assert body["customers"][0]["id"] == "cust_1"
    assert body["cursor"] == "next-page-token"


async def test_search_customers_builds_filter_from_provided_fields(mcp):
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post(f"{PROD_BASE}/customers/search").mock(
            return_value=httpx.Response(200, json={"customers": [{"id": "cust_2"}]})
        )
        result = await _call(
            mcp,
            "square_search_customers",
            {"email_address": "jane@example.com", "given_name": "Jane"},
        )

    sent_body = json.loads(route.calls.last.request.content)
    assert sent_body["query"]["filter"] == {
        "email_address": {"exact": "jane@example.com"},
        "given_name": {"exact": "Jane"},
    }
    body = json.loads(_text(result))
    assert body["customers"][0]["id"] == "cust_2"


async def test_get_customer_returns_detail_for_existing_id(mcp):
    with respx.mock(assert_all_called=True) as mock:
        mock.get(f"{PROD_BASE}/customers/cust_3").mock(
            return_value=httpx.Response(
                200, json={"customer": {"id": "cust_3", "given_name": "Jane"}}
            )
        )
        result = await _call(mcp, "square_get_customer", {"customer_id": "cust_3"})

    body = json.loads(_text(result))
    assert body["id"] == "cust_3"
    assert body["given_name"] == "Jane"


async def test_get_customer_returns_not_found_for_missing_id(mcp):
    with respx.mock(assert_all_called=True) as mock:
        mock.get(f"{PROD_BASE}/customers/missing").mock(
            return_value=httpx.Response(
                404, json={"errors": [{"code": "NOT_FOUND", "detail": "no such customer"}]}
            )
        )
        result = await _call(mcp, "square_get_customer", {"customer_id": "missing"})

    error = _error(result)
    assert error["code"] == "not_found"


# -- Catalog (AC13-AC14) -------------------------------------------------------


async def test_list_catalog_items_calls_list_endpoint_with_item_type(mcp):
    with respx.mock(assert_all_called=True) as mock:
        route = mock.get(f"{PROD_BASE}/catalog/list").mock(
            return_value=httpx.Response(
                200,
                json={
                    "objects": [{"id": "item_1", "type": "ITEM", "item_data": {"name": "Coffee"}}]
                },
            )
        )
        result = await _call(mcp, "square_list_catalog_items", {})

    assert route.calls.last.request.url.params["types"] == "ITEM"
    body = json.loads(_text(result))
    assert body["items"][0]["name"] == "Coffee"


async def test_get_catalog_item_existing_and_not_found(mcp):
    with respx.mock(assert_all_called=True) as mock:
        mock.get(f"{PROD_BASE}/catalog/object/item_1").mock(
            return_value=httpx.Response(
                200,
                json={"object": {"id": "item_1", "type": "ITEM", "item_data": {"name": "Coffee"}}},
            )
        )
        result = await _call(mcp, "square_get_catalog_item", {"object_id": "item_1"})
    body = json.loads(_text(result))
    assert body["name"] == "Coffee"

    with respx.mock(assert_all_called=True) as mock:
        mock.get(f"{PROD_BASE}/catalog/object/missing").mock(
            return_value=httpx.Response(404, json={"errors": [{"code": "NOT_FOUND"}]})
        )
        result = await _call(mcp, "square_get_catalog_item", {"object_id": "missing"})
    error = _error(result)
    assert error["code"] == "not_found"


# -- Orders (AC15-AC16) --------------------------------------------------------


async def test_search_orders_builds_filter_from_provided_fields(mcp):
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post(f"{PROD_BASE}/orders/search").mock(
            return_value=httpx.Response(200, json={"orders": [{"id": "order_1"}]})
        )
        result = await _call(
            mcp,
            "square_search_orders",
            {
                "location_ids": ["loc_1"],
                "state": "COMPLETED",
                "created_after": "2026-01-01T00:00:00Z",
                "cursor": "page-2",
            },
        )

    sent_body = json.loads(route.calls.last.request.content)
    assert sent_body["location_ids"] == ["loc_1"]
    assert sent_body["query"]["filter"]["state_filter"] == {"states": ["COMPLETED"]}
    assert sent_body["query"]["filter"]["date_time_filter"]["created_at"] == {
        "start_at": "2026-01-01T00:00:00Z"
    }
    assert sent_body["cursor"] == "page-2"
    body = json.loads(_text(result))
    assert body["orders"][0]["id"] == "order_1"


async def test_get_order_existing_and_not_found(mcp):
    with respx.mock(assert_all_called=True) as mock:
        mock.get(f"{PROD_BASE}/orders/order_1").mock(
            return_value=httpx.Response(200, json={"order": {"id": "order_1", "state": "OPEN"}})
        )
        result = await _call(mcp, "square_get_order", {"order_id": "order_1"})
    body = json.loads(_text(result))
    assert body["id"] == "order_1"

    with respx.mock(assert_all_called=True) as mock:
        mock.get(f"{PROD_BASE}/orders/missing").mock(
            return_value=httpx.Response(404, json={"errors": [{"code": "NOT_FOUND"}]})
        )
        result = await _call(mcp, "square_get_order", {"order_id": "missing"})
    error = _error(result)
    assert error["code"] == "not_found"


# -- Payments (AC17-AC18) -------------------------------------------------------


async def test_list_payments_passes_provided_filters_only(mcp):
    with respx.mock(assert_all_called=True) as mock:
        route = mock.get(f"{PROD_BASE}/payments").mock(
            return_value=httpx.Response(200, json={"payments": [{"id": "pay_1"}]})
        )
        await _call(mcp, "square_list_payments", {"location_id": "loc_1"})

    params = route.calls.last.request.url.params
    assert params["location_id"] == "loc_1"
    assert "begin_time" not in params
    assert "end_time" not in params
    assert "cursor" not in params


async def test_get_payment_existing_and_not_found(mcp):
    with respx.mock(assert_all_called=True) as mock:
        mock.get(f"{PROD_BASE}/payments/pay_1").mock(
            return_value=httpx.Response(
                200, json={"payment": {"id": "pay_1", "status": "COMPLETED"}}
            )
        )
        result = await _call(mcp, "square_get_payment", {"payment_id": "pay_1"})
    body = json.loads(_text(result))
    assert body["status"] == "COMPLETED"

    with respx.mock(assert_all_called=True) as mock:
        mock.get(f"{PROD_BASE}/payments/missing").mock(
            return_value=httpx.Response(404, json={"errors": [{"code": "NOT_FOUND"}]})
        )
        result = await _call(mcp, "square_get_payment", {"payment_id": "missing"})
    error = _error(result)
    assert error["code"] == "not_found"


# -- Inventory (AC19) -----------------------------------------------------------


async def test_get_inventory_count_returns_counts(mcp):
    with respx.mock(assert_all_called=True) as mock:
        route = mock.get(f"{PROD_BASE}/inventory/item_var_1").mock(
            return_value=httpx.Response(
                200,
                json={
                    "counts": [
                        {"catalog_object_id": "item_var_1", "location_id": "loc_1", "quantity": "5"}
                    ]
                },
            )
        )
        result = await _call(
            mcp,
            "square_get_inventory_count",
            {"catalog_object_id": "item_var_1", "location_ids": ["loc_1"]},
        )

    assert route.calls.last.request.url.params["location_ids"] == "loc_1"
    body = json.loads(_text(result))
    assert body[0]["quantity"] == "5"


# -- Refunds (AC20-AC22) --------------------------------------------------------


async def test_create_refund_generates_idempotency_key_when_omitted(mcp):
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post(f"{PROD_BASE}/refunds").mock(
            return_value=httpx.Response(
                200,
                json={
                    "refund": {
                        "id": "rfnd_1",
                        "status": "PENDING",
                        "amount_money": {"amount": 500, "currency": "USD"},
                    }
                },
            )
        )
        result = await _call(
            mcp,
            "square_create_refund",
            {"payment_id": "pay_1", "amount": 500, "currency": "USD"},
        )

    sent_body = json.loads(route.calls.last.request.content)
    assert sent_body["payment_id"] == "pay_1"
    assert sent_body["amount_money"] == {"amount": 500, "currency": "USD"}
    assert "idempotency_key" in sent_body and sent_body["idempotency_key"]

    body = json.loads(_text(result))
    assert body["id"] == "rfnd_1"
    assert body["status"] == "PENDING"


async def test_create_refund_is_idempotent_on_repeated_key(mcp):
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post(f"{PROD_BASE}/refunds").mock(
            return_value=httpx.Response(
                200,
                json={
                    "refund": {
                        "id": "rfnd_1",
                        "status": "PENDING",
                        "amount_money": {"amount": 500, "currency": "USD"},
                    }
                },
            )
        )
        args = {
            "payment_id": "pay_1",
            "amount": 500,
            "currency": "USD",
            "idempotency_key": "fixed-key-1",
        }
        result_1 = await _call(mcp, "square_create_refund", args)
        result_2 = await _call(mcp, "square_create_refund", args)

    assert route.call_count == 2
    first_body = json.loads(route.calls[0].request.content)
    second_body = json.loads(route.calls[1].request.content)
    assert first_body["idempotency_key"] == second_body["idempotency_key"] == "fixed-key-1"
    assert _text(result_1) == _text(result_2)


async def test_create_refund_maps_square_rejection_to_structured_error(mcp):
    with respx.mock(assert_all_called=True) as mock:
        mock.post(f"{PROD_BASE}/refunds").mock(
            return_value=httpx.Response(
                400,
                json={
                    "errors": [
                        {
                            "category": "INVALID_REQUEST_ERROR",
                            "code": "INSUFFICIENT_FUNDS",
                            "detail": "Refund amount exceeds the refundable balance.",
                        }
                    ]
                },
            )
        )
        result = await _call(
            mcp,
            "square_create_refund",
            {"payment_id": "pay_1", "amount": 999999, "currency": "USD"},
        )

    error = _error(result)
    assert error["code"] == "invalid_argument"
    assert "refundable balance" in error["message"]
    assert error["retryable"] is False
