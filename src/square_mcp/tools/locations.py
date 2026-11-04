from collections.abc import Callable

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from ..api_client import SquareClient
from ._common import dumps, run_tool


def _trim_location(loc: dict) -> dict:
    return {
        "id": loc.get("id"),
        "name": loc.get("name"),
        "status": loc.get("status"),
        "address": loc.get("address"),
        "timezone": loc.get("timezone"),
    }


def register(mcp: FastMCP, client_factory: Callable[[], SquareClient | None]) -> None:
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def square_list_locations() -> str:
        """List all business locations for the connected Square seller.

        No arguments. Returns every location on the account — Square does not
        paginate this endpoint.
        """

        async def _call(client: SquareClient) -> str:
            result = await client.get("/locations")
            locations = [_trim_location(loc) for loc in result.get("locations", [])]
            return dumps(locations)

        return await run_tool(client_factory, _call)
