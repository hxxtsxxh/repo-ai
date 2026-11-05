import unittest

from shop.app import create_app
from shop.errors import Conflict, OutOfStock


class OrderServiceTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.ctx = self.app.ctx
        self.svc = self.ctx.order_service

    def test_place_order_reserves_stock(self):
        order = self.svc.place_order("usr_9", [{"sku": "TEE-0001", "quantity": 2}], region="OR")
        self.assertEqual(order.status, "pending")
        self.assertEqual(self.ctx.inventory.available("TEE-0001"), 18)
        self.assertEqual(order.total_cents, 2 * 1999 + 599)

    def test_lines_are_merged(self):
        order = self.svc.place_order(
            "usr_9", [{"sku": "STK-0001"}, {"sku": "stk-0001", "quantity": 2}], region="OR"
        )
        self.assertEqual(len(order.lines), 1)
        self.assertEqual(order.lines[0].quantity, 3)

    def test_out_of_stock_rolls_back(self):
        with self.assertRaises(OutOfStock):
            self.svc.place_order(
                "usr_9", [{"sku": "TEE-0001", "quantity": 1}, {"sku": "MUG-0001", "quantity": 50}]
            )
        self.assertEqual(self.ctx.inventory.available("TEE-0001"), 20)

    def test_ship_commits_stock(self):
        order = self.svc.place_order("usr_9", [{"sku": "HAT-0001", "quantity": 2}])
        self.ctx.payment_service.capture(order.id)
        self.svc.ship(order.id)
        self.assertEqual(self.ctx.inventory.on_hand("HAT-0001"), 18)
        self.assertEqual(self.ctx.inventory.reserved("HAT-0001"), 0)

    def test_cancel_paid_order(self):
        order = self.svc.place_order("usr_9", [{"sku": "HAT-0001", "quantity": 2}])
        self.ctx.payment_service.capture(order.id)
        self.svc.cancel(order.id)
        self.assertEqual(self.ctx.inventory.available("HAT-0001"), 20)

    def test_cannot_cancel_shipped(self):
        order = self.svc.place_order("usr_9", [{"sku": "HAT-0001", "quantity": 1}])
        self.ctx.payment_service.capture(order.id)
        self.svc.ship(order.id)
        with self.assertRaises(Conflict):
            self.svc.cancel(order.id)


if __name__ == "__main__":
    unittest.main()
