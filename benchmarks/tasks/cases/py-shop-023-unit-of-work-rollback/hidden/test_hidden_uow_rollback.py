import unittest
from dataclasses import dataclass

from shop.app import create_app
from shop.errors import PaymentError
from shop.repository.memory import InMemoryRepository
from shop.repository.unit_of_work import UnitOfWork


@dataclass
class Box:
    id: str
    label: str
    tags: list


class Boom(Exception):
    pass


class UnitOfWorkTest(unittest.TestCase):
    def setUp(self):
        self.repo = InMemoryRepository()
        self.repo.add(Box("a", "alpha", ["x"]))
        self.repo.add(Box("b", "beta", []))

    def test_in_place_changes_are_undone(self):
        with self.assertRaises(Boom):
            with UnitOfWork(self.repo):
                box = self.repo.get("a")
                box.label = "changed"
                box.tags.append("y")
                self.repo.update(box)
                raise Boom()
        self.assertEqual(self.repo.get("a").label, "alpha")
        self.assertEqual(self.repo.get("a").tags, ["x"])

    def test_insert_and_delete_are_undone(self):
        with self.assertRaises(Boom):
            with UnitOfWork(self.repo):
                self.repo.add(Box("c", "gamma", []))
                self.repo.delete("b")
                raise Boom()
        self.assertEqual([b.id for b in self.repo.list()], ["a", "b"])

    def test_success_keeps_changes(self):
        with UnitOfWork(self.repo):
            box = self.repo.get("a")
            box.label = "kept"
            self.repo.update(box)
            self.repo.add(Box("c", "gamma", []))
        self.assertEqual(self.repo.get("a").label, "kept")
        self.assertEqual(len(self.repo), 3)

    def test_several_repositories(self):
        other = InMemoryRepository()
        other.add(Box("z", "zeta", []))
        with self.assertRaises(Boom):
            with UnitOfWork(self.repo, other):
                self.repo.get("b").label = "x"
                other.get("z").label = "y"
                raise Boom()
        self.assertEqual(self.repo.get("b").label, "beta")
        self.assertEqual(other.get("z").label, "zeta")


class RefundRollbackTest(unittest.TestCase):
    def setUp(self):
        self.ctx = create_app().ctx
        order = self.ctx.order_service.place_order("usr_9", [{"sku": "BAG-0001"}], region="OR")
        self.order_id = order.id
        self.payment_id = self.ctx.payment_service.capture(order.id).id

    def _gateway_down(self):
        def refuse(gateway_ref, amount_cents):
            raise PaymentError("gateway timeout")
        self.ctx.gateway.refund = refuse

    def _gateway_up(self):
        del self.ctx.gateway.refund

    def test_failed_full_refund_leaves_everything_untouched(self):
        self._gateway_down()
        with self.assertRaises(PaymentError):
            self.ctx.payment_service.refund(self.payment_id)
        payment = self.ctx.payments.get(self.payment_id)
        self.assertEqual(payment.refunded_cents, 0)
        self.assertEqual(payment.status, "captured")
        self.assertEqual(self.ctx.orders.get(self.order_id).status, "paid")
        self._gateway_up()
        payment = self.ctx.payment_service.refund(self.payment_id)
        self.assertEqual(payment.status, "refunded")
        self.assertEqual(self.ctx.orders.get(self.order_id).status, "refunded")
        self.assertEqual(len(self.ctx.gateway.refunds), 1)

    def test_failed_partial_refund_keeps_earlier_refund(self):
        self.ctx.payment_service.refund(self.payment_id, 1000)
        self._gateway_down()
        with self.assertRaises(PaymentError):
            self.ctx.payment_service.refund(self.payment_id, 500)
        payment = self.ctx.payments.get(self.payment_id)
        self.assertEqual(payment.refunded_cents, 1000)
        self.assertEqual(payment.status, "partially_refunded")


if __name__ == "__main__":
    unittest.main()
