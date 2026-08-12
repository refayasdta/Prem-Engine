from fastapi import FastAPI
from fastapi.testclient import TestClient
from prem_engine_api.rate_limit import RateLimitMiddleware, SlidingWindowRateLimiter


async def test_sliding_window_releases_expired_requests() -> None:
    limiter = SlidingWindowRateLimiter(limit=2, window_seconds=10)

    first = await limiter.consume("client", now=0)
    second = await limiter.consume("client", now=1)
    rejected = await limiter.consume("client", now=2)
    released = await limiter.consume("client", now=10.1)

    assert first.allowed is True
    assert first.remaining == 1
    assert second.allowed is True
    assert second.remaining == 0
    assert rejected.allowed is False
    assert rejected.reset_after_seconds == 8
    assert released.allowed is True
    assert released.remaining == 0


def test_api_requests_are_limited_with_retry_headers() -> None:
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, limit=2, window_seconds=60)

    @app.get("/api/probe")
    async def probe() -> dict[str, bool]:
        return {"ok": True}

    client = TestClient(app)
    first = client.get("/api/probe")
    second = client.get("/api/probe")
    rejected = client.get("/api/probe")

    assert first.status_code == 200
    assert first.headers["x-ratelimit-limit"] == "2"
    assert first.headers["x-ratelimit-remaining"] == "1"
    assert second.status_code == 200
    assert second.headers["x-ratelimit-remaining"] == "0"
    assert rejected.status_code == 429
    assert rejected.json() == {"detail": "Rate limit exceeded. Try again later."}
    assert rejected.headers["x-ratelimit-limit"] == "2"
    assert rejected.headers["x-ratelimit-remaining"] == "0"
    assert rejected.headers["retry-after"] == "60"
    assert rejected.headers["cache-control"] == "no-store"


def test_non_api_routes_are_not_limited() -> None:
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, limit=1, window_seconds=60)

    @app.get("/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    client = TestClient(app)

    assert client.get("/health").status_code == 200
    assert client.get("/health").status_code == 200
