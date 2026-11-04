from collections.abc import Callable

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from ..api_client import SquareClient
from ._common import dumps, run_tool


def _trim_payment(p: dict) -> dict:
    return {
        "id": p.get("id"),
        "status": p.get("status"),
        "amount_money": p.get("amount_money"),
        "order_id": p.get("order_id"),
        "location_id": p.get("location_id"),
        "created_at": p.get("created_at"),
        "updated_at": p.get("updated_at"),
    }


def register(mcp: FastMCP, client_factory: Callable[[], SquareClient | None]) -> None:
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def square_list_payments(
        location_id: str | None = None,
        begin_time: str | None = None,
        end_time: str | None = None,
        cursor: str | None = None,
    ) -> str:
        """List payments, optionally filtered by location and time range.

        Args:
            location_id: Restrict to payments at this location.
            begin_time: RFC 3339 timestamp; only payments at/after this time.
            end_time: RFC 3339 timestamp; only payments before this time.
            cursor: Pagination cursor from a previous call's response.
        """

        async def _call(client: SquareClient) -> str:
            result = await client.get(
                "/payments",
                params={
                    "location_id": location_id,
                    "begin_time": begin_time,
                    "end_time": end_time,
                    "cursor": cursor,
                },
            )
            payload: dict = {"payments": [_trim_payment(p) for p in result.get("payments", [])]}
            if result.get("cursor"):
                payload["cursor"] = result["cursor"]
            return dumps(payload)

        return await run_tool(client_factory, _call)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def square_get_payment(payment_id: str) -> str:
        """Get a single payment's detail by id.

        Args:
            payment_id: The Square payment id.
        """

        async def _call(client: SquareClient) -> str:
            result = await client.get(f"/payments/{payment_id}")
            return dumps(_trim_payment(result.get("payment", {})))

        return await run_tool(client_factory, _call)
