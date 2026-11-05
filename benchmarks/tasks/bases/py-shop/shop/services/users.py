"""Account registration and login."""

from shop.errors import AuthError, Conflict, ValidationError
from shop.models.user import User
from shop.services.auth import hash_password, issue_token, verify_password
from shop.utils.validation import is_valid_email

MIN_PASSWORD_LENGTH = 8


class UserService:
    def __init__(self, users):
        self.users = users

    def register(self, email: str, name: str, password: str, roles=("customer",)) -> User:
        email = (email or "").strip()
        if not is_valid_email(email):
            raise ValidationError("invalid email address")
        if self.users.by_email(email) is not None:
            raise Conflict("email already registered")
        if len(password or "") < MIN_PASSWORD_LENGTH:
            raise ValidationError(
                f"password must be at least {MIN_PASSWORD_LENGTH} characters"
            )
        user = User(
            id=self.users.next_id(),
            email=email,
            name=(name or "").strip() or email.split("@")[0],
            password_hash=hash_password(password),
            roles=list(roles),
        )
        return self.users.add(user)

    def authenticate(self, email: str, password: str, now=None) -> str:
        user = self.users.by_email(email or "")
        if user is None or not verify_password(password or "", user.password_hash):
            raise AuthError("invalid email or password")
        return issue_token(user.id, user.roles, now=now)
