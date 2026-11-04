import contextvars

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .api_client import SquareClient, SquareError
from .config import Settings, base_url_for

INSTRUCTIONS = (
    "Square MCP connects to a seller's Square point-of-sale / payments account. "
    "Use these tools to look up locations, customers, catalog items, orders, "
    "payments, and current inventory counts, and to issue a refund against a "
    "completed payment. A typical flow: find the customer or order first "
    "(square_search_customers / square_search_orders), then read the related "
    "payment (square_get_payment) before calling square_create_refund — refunds "
    "are irreversible money movement, so only call it when a refund was "
    "explicitly asked for. Pass X-Square-Environment: sandbox to exercise this "
    "service without touching a live Square business."
)

# ─────────────────────────────────────────────────────────────────────────────
# Per-request credential contextvars for gateway mode.
# GatewayCredentialMiddleware sets these before the MCP handler runs.
# Python asyncio copies context per task, so concurrent requests are isolated.
# ─────────────────────────────────────────────────────────────────────────────
_gateway_token_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "square_gateway_token", default=None
)
_gateway_environment_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "square_gateway_environment", default=None
)


def get_client_from_context(settings: Settings) -> SquareClient | None:
    """Resolve the active SquareClient for the current request context.

    Raises SquareError(invalid_argument) when X-Square-Environment carries a
    value other than "production"/"sandbox" (AC4) — this runs before any
    outbound Square call, so the tool layer never reaches the network with a
    bad environment.
    """
    if settings.auth_mode == "gateway":
        token = _gateway_token_var.get()
        environment = _gateway_environment_var.get() or "production"
    else:
        token = settings.square_access_token
        environment = settings.square_environment

    if not token:
        return None

    if environment not in ("production", "sandbox"):
        raise SquareError(
            400,
            "invalid_argument",
            f"Invalid X-Square-Environment value: {environment!r}; "
            "must be 'production' or 'sandbox'.",
            False,
        )

    return SquareClient(token, base_url_for(environment), settings.square_api_version)


class GatewayCredentialMiddleware:
    """ASGI middleware for gateway mode.

    Reads the configured credential headers from each /mcp request and stores
    them in contextvars for the duration of that request. Returns 401 if the
    access-token header is missing. An invalid (but present) environment value
    is NOT rejected here — that is a usage error, not a missing-credential
    error, so it is surfaced as a tool-level invalid_argument (AC4) instead.
    """

    def __init__(self, app: ASGIApp, settings: Settings):
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if not path.startswith("/mcp"):
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        # Header lookup is case-insensitive in Starlette.
        token = request.headers.get(self.settings.square_auth_header.lower())
        if not token:
            response = JSONResponse(
                {
                    "error": "Missing credentials",
                    "message": (
                        f"Gateway mode requires the {self.settings.square_auth_header} header"
                    ),
                    "required_headers": [self.settings.square_auth_header],
                },
                status_code=401,
            )
            await response(scope, receive, send)
            return

        environment = request.headers.get(self.settings.square_env_header.lower())

        token_ctx = _gateway_token_var.set(token)
        env_ctx = _gateway_environment_var.set(environment)
        try:
            await self.app(scope, receive, send)
        finally:
            _gateway_token_var.reset(token_ctx)
            _gateway_environment_var.reset(env_ctx)


def create_mcp_server(settings: Settings) -> FastMCP:
    """Build the FastMCP server instance and register all tools."""
    # DNS-rebinding protection is disabled because the container runs behind
    # mcp-gateway on an internal Docker network and is never publicly exposed.
    mcp = FastMCP(
        name="square-mcp",
        instructions=INSTRUCTIONS,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        stateless_http=True,
        json_response=True,
    )

    def client_factory() -> SquareClient | None:
        return get_client_from_context(settings)

    # Register all tool modules.
    from .tools import catalog, customers, inventory, locations, orders, payments, refunds

    locations.register(mcp, client_factory)
    customers.register(mcp, client_factory)
    catalog.register(mcp, client_factory)
    orders.register(mcp, client_factory)
    payments.register(mcp, client_factory)
    inventory.register(mcp, client_factory)
    refunds.register(mcp, client_factory)

    return mcp
