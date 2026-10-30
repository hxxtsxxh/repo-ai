"""User endpoints."""
from fastapi import APIRouter

from app.auth.login import login
from app.db.models import User

router = APIRouter()


@router.post("/login")
def post_login(email: str, password: str) -> dict:
    return {"token": login(email, password)}


@router.get("/users/{user_id}")
def get_user(user_id: int) -> User:
    return User(id=user_id, email="")
