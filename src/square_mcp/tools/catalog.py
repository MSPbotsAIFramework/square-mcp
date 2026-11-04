from collections.abc import Callable

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from ..api_client import SquareClient
from ._common import dumps, run_tool


def _trim_catalog_object(obj: dict) -> dict:
    trimmed = {"id": obj.get("id"), "type": obj.get("type"), "updated_at": obj.get("updated_at")}
    item_data = obj.get("item_data")
    if item_data:
        trimmed["name"] = item_data.get("name")
        trimmed["description"] = item_data.get("description")
        trimmed["variations"] = [
            {
                "id": v.get("id"),
                "name": (v.get("item_variation_data") or {}).get("name"),
                "price_money": (v.get("item_variation_data") or {}).get("price_money"),
            }
            for v in item_data.get("variations", [])
        ]
    return trimmed


def register(mcp: FastMCP, client_factory: Callable[[], SquareClient | None]) -> None:
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def square_list_catalog_items(cursor: str | None = None) -> str:
        """List catalog items (products) for the connected Square seller.

        Args:
            cursor: Pagination cursor from a previous call's response.
        """

        async def _call(client: SquareClient) -> str:
            result = await client.get("/catalog/list", params={"types": "ITEM", "cursor": cursor})
            payload: dict = {"items": [_trim_catalog_object(o) for o in result.get("objects", [])]}
            if result.get("cursor"):
                payload["cursor"] = result["cursor"]
            return dumps(payload)

        return await run_tool(client_factory, _call)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def square_get_catalog_item(object_id: str) -> str:
        """Get a single catalog object (item, variation, etc.) by id.

        Args:
            object_id: The Square catalog object id.
        """

        async def _call(client: SquareClient) -> str:
            result = await client.get(f"/catalog/object/{object_id}")
            return dumps(_trim_catalog_object(result.get("object", {})))

        return await run_tool(client_factory, _call)
