import uuid
from collections.abc import Callable

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from ..api_client import SquareClient
from ._common import dumps, run_tool


def _trim_refund(r: dict) -> dict:
    return {
        "id": r.get("id"),
        "status": r.get("status"),
        "amount_money": r.get("amount_money"),
        "payment_id": r.get("payment_id"),
        "created_at": r.get("created_at"),
    }


def register(mcp: FastMCP, client_factory: Callable[[], SquareClient | None]) -> None:
    @mcp.tool(
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True)
    )
    async def square_create_refund(
        payment_id: str,
        amount: int,
        currency: str,
        reason: str | None = None,
        idempotency_key: str | None = None,
    ) -> str:
        """Issue a refund against a completed payment. Irreversible.

        Args:
            payment_id: Square payment id to refund.
            amount: Refund amount in smallest currency unit (cents for USD).
            currency: ISO 4217 code, e.g. "USD".
            reason: Optional reason shown on the refund record.
            idempotency_key: Own key to dedupe retries; auto-generated if omitted.
        """

        async def _call(client: SquareClient) -> str:
            key = idempotency_key or str(uuid.uuid4())
            body: dict = {
                "payment_id": payment_id,
                "amount_money": {"amount": amount, "currency": currency},
            }
            if reason is not None:
                body["reason"] = reason
            result = await client.post("/refunds", json_body=body, idempotency_key=key)
            return dumps(_trim_refund(result.get("refund", {})))

        return await run_tool(client_factory, _call)
