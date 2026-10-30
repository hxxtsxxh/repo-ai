from shop.repository.memory import InMemoryRepository


class UserRepository(InMemoryRepository):
    entity = "user"
    id_prefix = "usr"

    def by_email(self, email: str):
        wanted = email.strip().lower()
        for user in self._items.values():
            if user.email.lower() == wanted:
                return user
        return None
