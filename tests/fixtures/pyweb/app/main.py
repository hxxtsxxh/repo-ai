"""Application entrypoint: wires routers and middleware."""
from fastapi import FastAPI

from app.api import bookings, users
from app.auth.middleware import AuthMiddleware

app = FastAPI(title="booking")
app.add_middleware(AuthMiddleware)
app.include_router(users.router)
app.include_router(bookings.router)


@app.get("/health")
def health() -> dict:
    return {"ok": True}
