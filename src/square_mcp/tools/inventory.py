from collections.abc import Callable

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from ..api_client import SquareClient
from ._common import dumps, run_tool


def _trim_count(c: dict) -> dict:
    return {
        "catalog_object_id": c.get("catalog_object_id"),
        "location_id": c.get("location_id"),
        "state": c.get("state"),
        "quantity": c.get("quantity"),
    }


def register(mcp: FastMCP, client_factory: Callable[[], SquareClient | None]) -> None:
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def square_get_inventory_count(
        catalog_object_id: str, location_ids: list[str] | None = None
    ) -> str:
        """Get current stock counts for a catalog item variation, per location.

        Args:
            catalog_object_id: The catalog object id (item variation) to check.
            location_ids: Restrict counts to these locations; all locations if omitted.
        """

        async def _call(client: SquareClient) -> str:
            params = {}
            if location_ids:
                params["location_ids"] = ",".join(location_ids)
            result = await client.get(f"/inventory/{catalog_object_id}", params=params)
            counts = [_trim_count(c) for c in result.get("counts", [])]
            return dumps(counts)

        return await run_tool(client_factory, _call)
