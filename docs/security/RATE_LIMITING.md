# Rate limiting

Prem Engine applies sliding-window rate limiting at both public application boundaries.

## Enforcement layers

| Boundary | Default | Identity | Purpose |
| --- | ---: | --- | --- |
| Next.js `/api/*` routes | 60 requests per 60 seconds | Vercel-provided client IP | Stops one browser or caller from flooding the public proxy |
| FastAPI `/api/*` routes | 300 requests per 60 seconds | Direct network peer | Protects each API instance and its database from excess upstream traffic |

The frontend prefers Vercel's `x-vercel-forwarded-for` request header, then falls back to
`x-forwarded-for` and `x-real-ip` for local or non-Vercel hosting. The backend deliberately does not
trust forwarded headers because the Cloud Run service may also be called directly. `/health`, API
documentation, static assets, and rendered pages are not counted; the data-bearing `/api` routes are.

Allowed responses expose:

- `X-RateLimit-Limit`
- `X-RateLimit-Remaining`
- `X-RateLimit-Reset` as a Unix timestamp

Rejected requests return HTTP `429` with the same budget headers, `Retry-After`, `Cache-Control:
no-store`, and this JSON body:

```json
{"detail":"Rate limit exceeded. Try again later."}
```

## Configuration

Configure the Next.js deployment with server-only environment variables:

```dotenv
PREM_ENGINE_RATE_LIMIT_ENABLED=true
PREM_ENGINE_RATE_LIMIT_REQUESTS=60
PREM_ENGINE_RATE_LIMIT_WINDOW_SECONDS=60
```

Configure the FastAPI deployment separately:

```dotenv
API_RATE_LIMIT_ENABLED=true
API_RATE_LIMIT_REQUESTS=300
API_RATE_LIMIT_WINDOW_SECONDS=60
```

Setting either `*_ENABLED` value to `false` disables only that layer. Limits and windows must be
positive integers; the frontend safely falls back to its defaults for invalid values, while backend
configuration fails fast during startup.

## Deployment limitation

The counters are intentionally bounded and in memory, so they do not add a database or paid cache to
the free-first architecture. A counter is local to one Vercel or Cloud Run runtime. This is a useful
application-level safety net, but it is not a globally coordinated denial-of-service control when
either service scales to multiple instances.

Before raising instance counts or traffic budgets, add a distributed edge limit through the hosting
platform or a shared low-latency counter store. Keep these application limits enabled as defense in
depth even after an edge control is introduced.
