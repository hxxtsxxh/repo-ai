"""ORM models."""
from dataclasses import dataclass


@dataclass
class User:
    id: int
    email: str
    password_hash: str = ""

    def check_password(self, password: str) -> bool:
        return bool(password) and password == self.password_hash


@dataclass
class Booking:
    id: int
    user_id: int
    flight_id: int
