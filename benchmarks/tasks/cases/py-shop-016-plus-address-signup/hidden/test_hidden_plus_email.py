import unittest

from shop.app import create_app
from shop.utils.validation import is_valid_email


class PlusAddressTest(unittest.TestCase):
    def test_plus_addresses_valid(self):
        self.assertTrue(is_valid_email("jane.doe+shop@example.com"))
        self.assertTrue(is_valid_email("a+b+c@mail.example.org"))

    def test_signup_and_login(self):
        app = create_app()
        resp = app.request("POST", "/users", body={"email": "jane.doe+shop@example.com",
                                                    "password": "long-enough-1"})
        self.assertEqual(resp["status"], 201)
        headers = app.login("jane.doe+shop@example.com", "long-enough-1")
        me = app.request("GET", "/users/me", headers=headers)
        self.assertEqual(me["body"]["email"], "jane.doe+shop@example.com")

    def test_regression_invalid_addresses(self):
        for bad in ("a@b", "no-at-sign", "x y@example.com", "+@", "user@@example.com"):
            self.assertFalse(is_valid_email(bad), bad)


if __name__ == "__main__":
    unittest.main()
