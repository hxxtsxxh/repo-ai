import unittest

from shop.api.router import Router
from shop.app import create_app
from shop.errors import NotFound


def _handler(name):
    def handler(ctx, request, **params):
        return {"status": 200, "body": {"handler": name, **params}}
    return handler


class NestedRouteTest(unittest.TestCase):
    def test_param_matches_single_segment(self):
        router = Router()
        router.add("GET /a/{x}", _handler("one"))
        router.add("GET /a/{x}/b", _handler("two"))
        handler, params = router.resolve("GET", "/a/1/b")
        self.assertEqual(params, {"x": "1"})
        self.assertEqual(handler(None, {})["body"]["handler"], "two")
        with self.assertRaises(NotFound):
            router.resolve("GET", "/a/1/b/c")

    def test_regression_trailing_slash(self):
        router = Router()
        router.add("GET /a/{x}", _handler("one"))
        self.assertEqual(router.resolve("GET", "/a/7/")[1], {"x": "7"})

    def test_order_payments_endpoint(self):
        app = create_app()
        headers = app.register_and_login("pat@example.com")
        order = app.request("POST", "/orders", headers=headers,
                            body={"items": [{"sku": "HAT-0001"}], "region": "OR"})["body"]
        self.assertEqual(app.request("POST", f"/orders/{order['id']}/pay", headers=headers)["status"], 200)
        resp = app.request("GET", f"/orders/{order['id']}/payments", headers=headers)
        self.assertEqual(resp["status"], 200)
        self.assertEqual(len(resp["body"]["items"]), 1)
        self.assertEqual(resp["body"]["items"][0]["order_id"], order["id"])
        self.assertEqual(app.request("GET", f"/orders/{order['id']}", headers=headers)["status"], 200)


if __name__ == "__main__":
    unittest.main()
