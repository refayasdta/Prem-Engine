"""Per-instance sliding-window rate limiting for public API routes."""

from __future__ import annotations

import asyncio
import math
import time
from collections import deque
from dataclasses import dataclass

from starlette.datastructures import MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    """Result of consuming one request from a rate-limit window."""

    allowed: bool
    limit: int
    remaining: int
    reset_after_seconds: int


class SlidingWindowRateLimiter:
    """Bounded in-memory sliding-window limiter keyed by request source."""

    def __init__(self, *, limit: int, window_seconds: int, max_keys: int = 10_000) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self.max_keys = max_keys
        self._requests: dict[str, deque[float]] = {}
        self._lock = asyncio.Lock()

    async def consume(self, key: str, *, now: float | None = None) -> RateLimitDecision:
        """Consume a request and return the current budget for ``key``."""

        observed_at = time.monotonic() if now is None else now
        cutoff = observed_at - self.window_seconds

        async with self._lock:
            timestamps = self._requests.get(key)
            if timestamps is None:
                self._make_room(observed_at)
                timestamps = deque()
                self._requests[key] = timestamps

            while timestamps and timestamps[0] <= cutoff:
                timestamps.popleft()

            allowed = len(timestamps) < self.limit
            if allowed:
                timestamps.append(observed_at)

            reset_after = (
                max(1, math.ceil(timestamps[0] + self.window_seconds - observed_at))
                if timestamps
                else self.window_seconds
            )
            return RateLimitDecision(
                allowed=allowed,
                limit=self.limit,
                remaining=max(0, self.limit - len(timestamps)),
                reset_after_seconds=reset_after,
            )

    def _make_room(self, now: float) -> None:
        if len(self._requests) < self.max_keys:
            return

        cutoff = now - self.window_seconds
        expired_keys = [
            key
            for key, timestamps in self._requests.items()
            if not timestamps or timestamps[-1] <= cutoff
        ]
        for key in expired_keys:
            del self._requests[key]

        if len(self._requests) >= self.max_keys:
            oldest_key = min(self._requests, key=lambda key: self._requests[key][-1])
            del self._requests[oldest_key]


class RateLimitMiddleware:
    """Apply rate limiting to ``/api`` routes without trusting forwarded headers."""

    def __init__(self, app: ASGIApp, *, limit: int, window_seconds: int) -> None:
        self.app = app
        self.limiter = SlidingWindowRateLimiter(limit=limit, window_seconds=window_seconds)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not _is_public_api_path(scope.get("path", "")):
            await self.app(scope, receive, send)
            return

        client = scope.get("client")
        client_host = client[0] if client is not None else "unknown"
        decision = await self.limiter.consume(client_host)
        headers = _rate_limit_headers(decision)

        if not decision.allowed:
            headers["Retry-After"] = str(decision.reset_after_seconds)
            headers["Cache-Control"] = "no-store"
            response = JSONResponse(
                {"detail": "Rate limit exceeded. Try again later."},
                status_code=429,
                headers=headers,
            )
            await response(scope, receive, send)
            return

        async def send_with_rate_limit_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                response_headers = MutableHeaders(scope=message)
                for name, value in headers.items():
                    response_headers[name] = value
            await send(message)

        await self.app(scope, receive, send_with_rate_limit_headers)


def _is_public_api_path(path: str) -> bool:
    return path == "/api" or path.startswith("/api/")


def _rate_limit_headers(decision: RateLimitDecision) -> dict[str, str]:
    reset_at = math.ceil(time.time() + decision.reset_after_seconds)
    return {
        "X-RateLimit-Limit": str(decision.limit),
        "X-RateLimit-Remaining": str(decision.remaining),
        "X-RateLimit-Reset": str(reset_at),
    }
