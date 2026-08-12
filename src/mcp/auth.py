# Intentions: exact-token-match auth for the MCP HTTP surface. A Starlette middleware wrapping the MCP ASGI
# app checks the Authorization: Bearer <token> header against the server's configured token. Deliberately
# simple (spec: exact match, tokens distributed by hand) -- not OAuth. Each MCP passes its own token so read
# and admin are gated independently. Also the transport-security (allowed Host) helper both servers share.
# References: docs/spec.md sections 5, 8.

from mcp.server.transport_security import TransportSecuritySettings
from starlette.types import ASGIApp, Receive, Scope, Send

from src.config import settings


def transport_security() -> TransportSecuritySettings | None:
    """TransportSecuritySettings allowing the configured public host(s) (settings.mcp_allowed_hosts). Behind
    a reverse proxy the public host must be allowed or the app returns 421 Misdirected Request. localhost is
    always included. None (SDK default: localhost-only) when no public host is configured."""
    hosts = [h.strip() for h in settings.mcp_allowed_hosts.split(",") if h.strip()]
    if not hosts:
        return None
    allowed = [*hosts, "localhost", "127.0.0.1"]
    origins = [f"https://{h}" for h in hosts] + [f"http://{h}" for h in hosts]
    return TransportSecuritySettings(allowed_hosts=allowed, allowed_origins=origins)


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
