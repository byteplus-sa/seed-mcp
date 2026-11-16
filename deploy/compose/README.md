# Docker Compose Kit: BYOK Foundation

Runs one Seed MCP instance behind Caddy TLS. Only Caddy is exposed.
Clients provide their own provider keys and a locally generated client secret
in private HTTP headers. There is no signup, OAuth or server-issued MCP key,
and no Redis task worker on HTTP.

The operator supplies `MCP_IDENTITY_HMAC_KEY`, not customer provider keys.
Keep it stable to preserve ownership, and use a fresh state volume. This kit
is single-instance; durable submission recovery, PostgreSQL and public-launch
hardening remain follow-up work.

```bash
cp .env.example .env    # then fill in every REQUIRED value
docker compose up -d --build
```

| File | Purpose |
|---|---|
| `compose.yaml` | Services, networks, volumes, and the pinned security settings |
| `Caddyfile` | TLS, request size limit, streaming, and blocking `/metrics` and `/ready` from outside |
| `.env.example` | Hostname, operator HMAC configuration and bounded HTTP/state limits |

Full setup and security limitations: [docs/self-hosting.md](../../docs/self-hosting.md).
