"""Database session factory."""


class Session:
    def find_user(self, email: str):
        return None


def get_session() -> Session:
    return Session()
