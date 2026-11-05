"""JWT issuance and verification."""
import time

import jwt

TOKEN_TTL_SECONDS = 3600


def issue_token(user_id: int, secret: str = "") -> str:
    payload = {"sub": user_id, "exp": int(time.time()) + TOKEN_TTL_SECONDS}
    return jwt.encode(payload, secret or "dev", algorithm="HS256")


def verify_token(token: str, secret: str = "") -> dict:
    return jwt.decode(token, secret or "dev", algorithms=["HS256"])
