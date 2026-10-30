"""Request middleware that attaches the authenticated user."""
from app.auth.tokens import verify_token


class AuthMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        headers = dict(scope.get("headers") or [])
        token = headers.get(b"authorization", b"").decode().removeprefix("Bearer ")
        scope["user"] = verify_token(token) if token else None
        await self.app(scope, receive, send)
