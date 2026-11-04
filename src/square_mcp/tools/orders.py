from collections.abc import Callable

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from ..api_client import SquareClient
from ._common import dumps, run_tool


def _trim_order(order: dict) -> dict:
    return {
        "id": order.get("id"),
        "location_id": order.get("location_id"),
        "state": order.get("state"),
        "created_at": order.get("created_at"),
        "updated_at": order.get("updated_at"),
        "total_money": order.get("total_money"),
    }


def register(mcp: FastMCP, client_factory: Callable[[], SquareClient | None]) -> None:
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def square_search_orders(
        location_ids: list[str],
        state: str | None = None,
        created_after: str | None = None,
        created_before: str | None = None,
        cursor: str | None = None,
    ) -> str:
        """Search orders across one or more locations.

        Args:
            location_ids: Location ids to search within (required by Square).
            state: Order state filter, e.g. "OPEN", "COMPLETED", "CANCELED".
            created_after: RFC 3339 timestamp; only orders created at/after this.
            created_before: RFC 3339 timestamp; only orders created before this.
            cursor: Pagination cursor from a previous call's response.
        """

        async def _call(client: SquareClient) -> str:
            body: dict = {"location_ids": location_ids}
            filter_: dict = {}
            if state is not None:
                filter_["state_filter"] = {"states": [state]}
            date_filter: dict = {}
            if created_after is not None:
                date_filter["start_at"] = created_after
            if created_before is not None:
                date_filter["end_at"] = created_before
            if date_filter:
                filter_["date_time_filter"] = {"created_at": date_filter}
            if filter_:
                body["query"] = {"filter": filter_}
            if cursor is not None:
                body["cursor"] = cursor
            result = await client.post("/orders/search", json_body=body)
            payload: dict = {"orders": [_trim_order(o) for o in result.get("orders", [])]}
            if result.get("cursor"):
                payload["cursor"] = result["cursor"]
            return dumps(payload)

        return await run_tool(client_factory, _call)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def square_get_order(order_id: str) -> str:
        """Get a single order's detail by id.

        Args:
            order_id: The Square order id.
        """

        async def _call(client: SquareClient) -> str:
            result = await client.get(f"/orders/{order_id}")
            return dumps(_trim_order(result.get("order", {})))

        return await run_tool(client_factory, _call)
