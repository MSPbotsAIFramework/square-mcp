# square-mcp

Stateless HTTP MCP service for the [Square](https://developer.squareup.com/docs/) POS/payments API. Exposes a seller's Square data as MCP tools so AI assistants can query locations, customers, catalog items, orders, payments, and current inventory counts, and issue a refund against a completed payment.

<div align="center">

## MSPbots Connector

**The MCP Gateway built for MSPs: visible, controlled, and your data stays where it belongs.**

[**Get started at connect.mspbots.ai →**](https://connect.mspbots.ai)

</div>

---

MSPbots Connector gives your AI clients one MCP URL to reach your entire MSP stack (RMM, PSA, documentation, security, finance), and gives you control over who can call which tool and a record of everything that was called.

**Hosted service: [connect.mspbots.ai](https://connect.mspbots.ai)** · Free to use.

### Why Connector

![MSPbots Connector](https://stgoss.mspbots.ai/files/mcp/mspbots-mcp.png)

| | |
|---|---|
| **Visible** | Every tool call is logged: who, which vendor, when. Usage dashboard, CSV export, SIEM streaming. |
| **Controlled** | Role-based, per-tool allowlist. Deny by default. |
| **Protected** | Credentials encrypted per record. AI clients never see your vendor passwords or tokens. |
| **MSP-native** | Built for the MSP stack only: RMM, PSA, documentation, security, finance. |

### Quick start

1. **Sign up** at [connect.mspbots.ai](https://connect.mspbots.ai).
2. **Connect your vendors.** Pick from 150+ connectors and authorize each one on the vendor's own page, or bring your own API keys. No extra vendor accounts needed.
3. **Set access.** Create roles and decide which tools each role may call. Nothing is allowed until you allow it.
4. **Add your MCP URL to your AI client.** Copy the URL from your Connector dashboard into Claude, ChatGPT, Cursor, VS Code, Gemini, Codex, or any MCP-capable client.
5. **Ask your AI to do real work**, and watch every call appear in the audit log.

### Features

**Unified gateway**
- One MCP URL for all your AI clients
- 150+ connectors across the MSP stack
- Custom MCP servers supported, free
- Authorization happens on each vendor's own page; the AI never sees passwords or tokens
- Bring your own credentials: use the vendor API keys you already have
- Multiple accounts per app; connect once, reuse across AI clients
- Tool search: finds the right action for the task
- One sign-in; vendor credentials are injected behind the scenes and OAuth tokens refresh automatically

**Visibility**
- Audit log for every tool call (who, which vendor, when)
- Usage dashboard: call volume, top vendors, error rate, per-user activity
- Export audit logs to CSV, or stream to Loki, Graylog, or LogScale (SIEM)
- Optional recording of tool arguments and result summaries (off by default, enabled per organization)

**Control**
- Per-role, per-tool allowlist, deny by default
- owner / admin / member roles
- SCIM provisioning with Entra ID, Okta, JumpCloud, and Google Workspace

**Security**
- Credentials encrypted one record at a time (AES-256-GCM, per-record key)
- AI clients authenticate with OAuth 2.1 + PKCE
- Vendor responses are scanned for prompt-injection patterns and returned as structured data. This is one layer of defense, not a guarantee against every attack.
- Static egress IP for customer firewall and API allowlisting

### Pricing

**Free.**

Links: [connect.mspbots.ai](https://connect.mspbots.ai) · [mspbots.ai](https://mspbots.ai)

---

## Architecture

- **Stateless** — no user state or credentials stored between requests
- **Per-request auth** — access token passed via `X-Square-Access-Token` header on every call
- **Concurrent-safe** — Python `contextvars` isolate credentials across parallel requests
- **Transports** — HTTP (production) or stdio (development)

## Endpoints

| Endpoint | Description |
|----------|-------------|
| `POST /mcp` | MCP protocol entry point (JSON-RPC) |
| `GET /health` | Health check |

Default port: **8080**

## Authorization

Pass your Square access token (Personal Access Token, or an OAuth access token you already have) in every `/mcp` request:

```
X-Square-Access-Token: <your_access_token>
X-Square-Environment: production   # optional, "production" (default) or "sandbox"
```

The service forwards the token as `Authorization: Bearer <token>` to the Square API. Tokens are never stored globally — each request is fully isolated.

## Authentication headers

| Header | Required | Meaning | Where to get it |
|---|---|---|---|
| `X-Square-Access-Token` | Yes | Square Personal Access Token, or a pre-obtained OAuth access token | Square Developer Dashboard → your application → Credentials (or OAuth) |
| `X-Square-Environment` | No | `production` (default) or `sandbox` — selects the Square API base URL | — |

## Tool List

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `square_list_locations` | List all business locations | — |
| `square_list_customers` | List customers | `cursor`, `limit` |
| `square_search_customers` | Search customers by exact-match fields | `phone_number`, `email_address`, `given_name`, `family_name`, `cursor` |
| `square_get_customer` | Get a single customer by id | `customer_id` |
| `square_list_catalog_items` | List catalog items (products) | `cursor` |
| `square_get_catalog_item` | Get a single catalog object by id | `object_id` |
| `square_search_orders` | Search orders across one or more locations | `location_ids`, `state`, `created_after`, `created_before`, `cursor` |
| `square_get_order` | Get a single order by id | `order_id` |
| `square_list_payments` | List payments | `location_id`, `begin_time`, `end_time`, `cursor` |
| `square_get_payment` | Get a single payment by id | `payment_id` |
| `square_get_inventory_count` | Get current stock counts for a catalog item variation | `catalog_object_id`, `location_ids` |
| `square_create_refund` | Issue a refund against a completed payment (destructive, idempotent) | `payment_id`, `amount`, `currency`, `reason`, `idempotency_key` |

### Parameter Details

**Pagination** (list/search tools): `cursor` is the token returned in a previous response's `cursor` field; omit on the first call.

**`square_search_orders` state values:** `OPEN`, `COMPLETED`, `CANCELED` (per Square's `OrderState`).

**`square_create_refund` amount:** integer, in the currency's smallest unit (e.g. cents for `USD`); `currency` is an ISO 4217 code.

## Quick Start

### Local development (env mode)

```bash
# Copy and edit environment config
cp .env.example .env
# Set SQUARE_ACCESS_TOKEN and AUTH_MODE=env in .env

# Install dependencies
uv sync

# Run the server
MCP_TRANSPORT=http AUTH_MODE=env python -m square_mcp
```

### Docker (gateway mode — production)

```bash
docker build -t square-mcp .
docker run -p 8080:8080 -e AUTH_MODE=gateway square-mcp
```

Or with Docker Compose:

```bash
docker compose up
```

## Test Examples

**Health check:**

```bash
curl http://localhost:8080/health
# {"status":"ok","transport":"http","auth_mode":"gateway"}
```

**List locations:**

```bash
curl -X POST http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "X-Square-Access-Token: <your_access_token>" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "square_list_locations",
      "arguments": {}
    }
  }'
```

**Search customers (sandbox):**

```bash
curl -X POST http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "X-Square-Access-Token: <your_access_token>" \
  -H "X-Square-Environment: sandbox" \
  -d '{
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/call",
    "params": {
      "name": "square_search_customers",
      "arguments": {"email_address": "jane@example.com"}
    }
  }'
```

**Issue a refund:**

```bash
curl -X POST http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "X-Square-Access-Token: <your_access_token>" \
  -d '{
    "jsonrpc": "2.0",
    "id": 3,
    "method": "tools/call",
    "params": {
      "name": "square_create_refund",
      "arguments": {"payment_id": "<payment_id>", "amount": 500, "currency": "USD", "reason": "Customer requested"}
    }
  }'
```

## Configuration Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `SQUARE_ACCESS_TOKEN` | — | Access token (env mode only) |
| `SQUARE_API_VERSION` | `2024-07-17` | `Square-Version` header pinned by this service |
| `SQUARE_AUTH_HEADER` | `X-Square-Access-Token` | MCP request header carrying the token |
| `SQUARE_ENV_HEADER` | `X-Square-Environment` | MCP request header selecting production/sandbox |
| `MCP_TRANSPORT` | `stdio` | `http` for production, `stdio` for local dev |
| `MCP_HTTP_PORT` | `8080` | HTTP listen port |
| `MCP_HTTP_HOST` | `0.0.0.0` | HTTP listen host |
| `AUTH_MODE` | `gateway` | `gateway` (per-request, SOP-compliant) or `env` (dev only) |
