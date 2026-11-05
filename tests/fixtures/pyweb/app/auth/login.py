"""Login flow: credential validation and token issuance."""
from app.auth.tokens import issue_token
from app.db.models import User
from app.db.session import get_session


class LoginError(Exception):
    """Raised when credentials are rejected."""


def validate_credentials(email: str, password: str) -> User:
    """Check the email/password pair against the stored hash."""
    if not email or "@" not in email:
        raise LoginError("invalid email")
    session = get_session()
    user = session.find_user(email)
    if user is None or not user.check_password(password):
        raise LoginError("bad credentials")
    return user


def login(email: str, password: str) -> str:
    user = validate_credentials(email, password)
    return issue_token(user.id)
