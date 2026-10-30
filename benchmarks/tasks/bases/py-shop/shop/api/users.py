"""Account endpoints."""

from shop.api.middleware import current_user
from shop.api.responses import created, json_response
from shop.api.serializers import serialize_user
from shop.errors import NotFound
from shop.utils.validation import require_fields


def register(ctx, request):
    body = request.get("body") or {}
    require_fields(body, "email", "password")
    user = ctx.user_service.register(body["email"], body.get("name", ""), body["password"])
    return created(serialize_user(user))


def login(ctx, request):
    body = request.get("body") or {}
    require_fields(body, "email", "password")
    token = ctx.user_service.authenticate(body["email"], body["password"])
    return json_response({"token": token, "token_type": "Bearer"})


def me(ctx, request):
    payload = current_user(ctx, request)
    user = ctx.users.get(payload["sub"])
    if user is None:
        raise NotFound("user not found")
    return json_response(serialize_user(user))
