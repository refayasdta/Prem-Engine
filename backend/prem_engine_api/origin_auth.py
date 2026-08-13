"""Authenticate server-to-server requests at the public API origin boundary."""

from __future__ import annotations

import hmac

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

ORIGIN_TOKEN_HEADER = b"x-prem-engine-origin-token"


class OriginAuthenticationMiddleware:
    """Require one configured origin token for every ``/api`` request."""

    def __init__(self, app: ASGIApp, *, tokens: tuple[str, ...]) -> None:
        if not tokens:
            raise ValueError("at least one origin token is required")
        self.app = app
        self._tokens = tuple(token.encode() for token in tokens)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = str(scope.get("path", ""))
        if scope["type"] != "http" or not (path == "/api" or path.startswith("/api/")):
            await self.app(scope, receive, send)
            return

        supplied = next(
            (value for name, value in scope.get("headers", []) if name == ORIGIN_TOKEN_HEADER),
            b"",
        )
        authenticated = False
        for expected in self._tokens:
            authenticated |= hmac.compare_digest(supplied, expected)
        if not authenticated:
            response = JSONResponse(
                {"detail": "Unauthorized"},
                status_code=401,
                headers={"Cache-Control": "no-store"},
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)
