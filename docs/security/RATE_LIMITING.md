# Rate limiting

Prem Engine applies in-memory sliding-window limits at both local application boundaries.

| Boundary | Default | Identity | Purpose |
| --- | ---: | --- | --- |
| Next.js `/api/*` proxy | 60 requests per 60 seconds | Browser network address | Prevents one local client from flooding the proxy |
| FastAPI `/api/*` routes | 300 requests per 60 seconds | Direct Compose network peer | Protects the API and database from excess traffic |

Allowed responses include `X-RateLimit-Limit`, `X-RateLimit-Remaining`, and
`X-RateLimit-Reset`. Rejected requests return HTTP 429, `Retry-After`, `Cache-Control: no-store`,
and a short JSON error.

The frontend settings are server-only:

```dotenv
PREM_ENGINE_RATE_LIMIT_ENABLED=true
PREM_ENGINE_RATE_LIMIT_REQUESTS=60
PREM_ENGINE_RATE_LIMIT_WINDOW_SECONDS=60
```

FastAPI is configured independently:

```dotenv
API_RATE_LIMIT_ENABLED=true
API_RATE_LIMIT_REQUESTS=300
API_RATE_LIMIT_WINDOW_SECONDS=60
```

These counters are intentionally process-local. That is sufficient for the single-installation
Compose topology and avoids another database or cache dependency. They are a safety boundary, not a
replacement for router/firewall controls: keep the default host-only frontend binding unless trusted
LAN access is deliberately enabled, and never publish the backend or PostgreSQL ports.
