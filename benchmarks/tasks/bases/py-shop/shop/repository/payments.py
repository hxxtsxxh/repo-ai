from shop.repository.memory import InMemoryRepository


class PaymentRepository(InMemoryRepository):
    entity = "payment"
    id_prefix = "pay"

    def for_order(self, order_id: str) -> list:
        return self.list(lambda p: p.order_id == order_id)

    def find_by_idempotency_key(self, key: str):
        for payment in self._items.values():
            if payment.idempotency_key == key:
                return payment
        return None
