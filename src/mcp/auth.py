# Intentions: exact-token-match auth for the MCP HTTP surface. A Starlette middleware wrapping the MCP ASGI
# app checks the Authorization: Bearer <token> header against the server's configured token. Deliberately
# simple (spec: exact match, tokens distributed by hand) -- not OAuth. Each MCP passes its own token so read
# and admin are gated independently. References: docs/spec.md sections 5, 8.

from starlette.types import ASGIApp, Receive, Scope, Send


class BearerTokenMiddleware:
    """Reject any HTTP request whose Authorization bearer != the expected token (401). Non-HTTP scopes
    (lifespan) pass through untouched."""

    def __init__(self, app: ASGIApp, expected_token: str) -> None:
        self.app = app
        self.expected_token = expected_token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        if self._authorized(scope):
            await self.app(scope, receive, send)
            return
        await self._reject(send)

    def _authorized(self, scope: Scope) -> bool:
        # empty expected_token = auth disabled (local/dev convenience). Otherwise require exact bearer match.
        if not self.expected_token:
            return True
        headers = dict(scope.get("headers") or [])
        auth = headers.get(b"authorization", b"").decode()
        return auth == f"Bearer {self.expected_token}"

    async def _reject(self, send: Send) -> None:
        await send({"type": "http.response.start", "status": 401,
                    "headers": [(b"content-type", b"text/plain")]})
        await send({"type": "http.response.body", "body": b"unauthorized"})
