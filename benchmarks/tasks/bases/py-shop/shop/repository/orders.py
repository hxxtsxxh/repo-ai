from shop.repository.memory import InMemoryRepository


class OrderRepository(InMemoryRepository):
    entity = "order"
    id_prefix = "ord"

    def for_user(self, user_id: str) -> list:
        return self.list(lambda o: o.user_id == user_id)

    def with_status(self, status: str) -> list:
        return self.list(lambda o: o.status == status)
