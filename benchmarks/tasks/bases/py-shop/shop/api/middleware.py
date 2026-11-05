"""Request helpers: headers, query parameters and authentication."""

from shop.errors import AuthError, ValidationError
from shop.services.auth import require_role, verify_token


def get_header(request: dict, name: str, default=None):
    """Header lookup. HTTP header names are case-insensitive."""
    wanted = name.lower()
    for key, value in (request.get("headers") or {}).items():
        if key.lower() == wanted:
            return value
    return default


def query_int(request: dict, name: str, default=None):
    raw = (request.get("query") or {}).get(name)
    if raw in (None, ""):
        return default
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"query parameter {name} must be an integer") from exc


def current_user(ctx, request: dict) -> dict:
    header = get_header(request, "Authorization")
    if not header or not header.startswith("Bearer "):
        raise AuthError("missing bearer token")
    return verify_token(header[len("Bearer ") :].strip())


def require_admin(ctx, request: dict) -> dict:
    payload = current_user(ctx, request)
    require_role(payload, "admin")
    return payload


def is_admin(payload: dict) -> bool:
    return "admin" in payload.get("roles", [])
