"""Password hashing and HMAC-signed access tokens.

Token format: ``<base64url(json payload)>.<hex hmac-sha256>``.
"""

import base64
import hashlib
import hmac
import json
import os
import time

from shop import config
from shop.errors import AuthError, Forbidden


def hash_password(password: str, salt=None) -> str:
    salt = salt or os.urandom(8).hex()
    iterations = config.PASSWORD_HASH_ITERATIONS
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), iterations)
    return f"pbkdf2${iterations}${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iterations, salt, expected = stored.split("$")
    except ValueError:
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iterations))
    return hmac.compare_digest(digest.hex(), expected)


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def _sign(body: str) -> str:
    return hmac.new(config.TOKEN_SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()


def issue_token(user_id: str, roles=(), now=None) -> str:
    issued_at = int(time.time() if now is None else now)
    ttl = config.TOKEN_TTL_MINUTES * 60
    payload = {"sub": user_id, "roles": list(roles), "iat": issued_at, "exp": issued_at + ttl}
    body = _b64encode(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
    return f"{body}.{_sign(body)}"


def verify_token(token: str, now=None) -> dict:
    if not isinstance(token, str) or token.count(".") != 1:
        raise AuthError("malformed token")
    body, signature = token.split(".")
    expected = _sign(body)
    if not hmac.compare_digest(signature, expected):
        raise AuthError("invalid token signature")
    try:
        payload = json.loads(_b64decode(body))
    except (ValueError, UnicodeDecodeError) as exc:
        raise AuthError("malformed token") from exc
    current = time.time() if now is None else now
    if current >= payload["exp"]:
        raise AuthError("token expired")
    return payload


def require_role(payload: dict, role: str) -> None:
    if role not in payload.get("roles", []):
        raise Forbidden(f"{role} role required")
