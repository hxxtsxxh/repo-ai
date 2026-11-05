import unittest

from shop.app import create_app
from shop.errors import Conflict


class CancelRestockTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.ctx = self.app.ctx

    def test_cancel_unpaid_order_releases_stock(self):
        order = self.ctx.order_service.place_order("usr_1", [{"sku": "HAT-0001", "quantity": 2}])
        self.assertEqual(self.ctx.inventory.available("HAT-0001"), 18)
        self.ctx.order_service.cancel(order.id)
        self.assertEqual(self.ctx.inventory.available("HAT-0001"), 20)
        self.assertEqual(self.ctx.inventory.reserved("HAT-0001"), 0)

    def test_cancel_via_api(self):
        headers = self.app.register_and_login("kim@example.com")
        order = self.app.request("POST", "/orders", headers=headers,
                                 body={"items": [{"sku": "MUG-0001", "quantity": 3}]})["body"]
        resp = self.app.request("POST", f"/orders/{order['id']}/cancel", headers=headers)
        self.assertEqual(resp["status"], 200)
        self.assertEqual(resp["body"]["status"], "cancelled")
        self.assertEqual(self.ctx.inventory.available("MUG-0001"), 20)

    def test_regression_paid_cancel_and_shipped(self):
        order = self.ctx.order_service.place_order("usr_1", [{"sku": "HAT-0001", "quantity": 2}])
        self.ctx.payment_service.capture(order.id)
        self.ctx.order_service.cancel(order.id)
        self.assertEqual(self.ctx.inventory.available("HAT-0001"), 20)
        shipped = self.ctx.order_service.place_order("usr_1", [{"sku": "HAT-0001", "quantity": 1}])
        self.ctx.payment_service.capture(shipped.id)
        self.ctx.order_service.ship(shipped.id)
        with self.assertRaises(Conflict):
            self.ctx.order_service.cancel(shipped.id)
        self.assertEqual(self.ctx.inventory.on_hand("HAT-0001"), 19)
        self.assertEqual(self.ctx.inventory.available("HAT-0001"), 19)


if __name__ == "__main__":
    unittest.main()
