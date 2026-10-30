import unittest

from shop.api.router import Router
from shop.errors import MethodNotAllowed, NotFound


def _handler(name):
    def handler(ctx, request, **params):
        return {"status": 200, "body": {"handler": name, **params}}
    return handler


class RouterTest(unittest.TestCase):
    def setUp(self):
        self.router = Router()
        self.router.add("GET /things", _handler("list"))
        self.router.add("GET /things/{thing_id}", _handler("get"))

    def test_static_route(self):
        handler, params = self.router.resolve("GET", "/things")
        self.assertEqual(params, {})

    def test_param_route(self):
        handler, params = self.router.resolve("GET", "/things/abc")
        self.assertEqual(params, {"thing_id": "abc"})

    def test_trailing_slash_and_query(self):
        _, params = self.router.resolve("GET", "/things/abc/?x=1")
        self.assertEqual(params, {"thing_id": "abc"})

    def test_not_found(self):
        with self.assertRaises(NotFound):
            self.router.resolve("GET", "/nope")

    def test_method_not_allowed(self):
        with self.assertRaises(MethodNotAllowed):
            self.router.resolve("DELETE", "/things")

    def test_dispatch_error(self):
        resp = self.router.dispatch(None, {"method": "GET", "path": "/missing"})
        self.assertEqual(resp["status"], 404)


if __name__ == "__main__":
    unittest.main()
