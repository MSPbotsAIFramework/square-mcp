from collections.abc import Callable

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from ..api_client import SquareClient
from ._common import dumps, run_tool


def _trim_customer(c: dict) -> dict:
    return {
        "id": c.get("id"),
        "given_name": c.get("given_name"),
        "family_name": c.get("family_name"),
        "email_address": c.get("email_address"),
        "phone_number": c.get("phone_number"),
        "created_at": c.get("created_at"),
    }


def register(mcp: FastMCP, client_factory: Callable[[], SquareClient | None]) -> None:
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def square_list_customers(cursor: str | None = None, limit: int | None = None) -> str:
        """List customers in the connected Square seller's directory.

        Args:
            cursor: Pagination cursor from a previous call's response.
            limit: Max results per page (Square's own default/limit applies).
        """

        async def _call(client: SquareClient) -> str:
            result = await client.get("/customers", params={"cursor": cursor, "limit": limit})
            payload: dict = {"customers": [_trim_customer(c) for c in result.get("customers", [])]}
            if result.get("cursor"):
                payload["cursor"] = result["cursor"]
            return dumps(payload)

        return await run_tool(client_factory, _call)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def square_search_customers(
        phone_number: str | None = None,
        email_address: str | None = None,
        given_name: str | None = None,
        family_name: str | None = None,
        cursor: str | None = None,
    ) -> str:
        """Search customers by one or more exact-match fields.

        Args:
            phone_number: Exact phone number to match.
            email_address: Exact email address to match.
            given_name: Exact given (first) name to match.
            family_name: Exact family (last) name to match.
            cursor: Pagination cursor from a previous response.
        """

        async def _call(client: SquareClient) -> str:
            filter_: dict = {}
            if phone_number is not None:
                filter_["phone_number"] = {"exact": phone_number}
            if email_address is not None:
                filter_["email_address"] = {"exact": email_address}
            if given_name is not None:
                filter_["given_name"] = {"exact": given_name}
            if family_name is not None:
                filter_["family_name"] = {"exact": family_name}
            body: dict = {"query": {"filter": filter_}}
            if cursor is not None:
                body["cursor"] = cursor
            result = await client.post("/customers/search", json_body=body)
            payload: dict = {"customers": [_trim_customer(c) for c in result.get("customers", [])]}
            if result.get("cursor"):
                payload["cursor"] = result["cursor"]
            return dumps(payload)

        return await run_tool(client_factory, _call)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def square_get_customer(customer_id: str) -> str:
        """Get a single customer's detail by id.

        Args:
            customer_id: The Square customer id.
        """

        async def _call(client: SquareClient) -> str:
            result = await client.get(f"/customers/{customer_id}")
            return dumps(_trim_customer(result.get("customer", {})))

        return await run_tool(client_factory, _call)
