import unittest
from unittest import mock

from shop import config
from shop.errors import AuthError
from shop.services.auth import issue_token, verify_token

T0 = 1_700_000_000


class SessionLifetimeTest(unittest.TestCase):
    def test_token_valid_for_an_hour(self):
        token = issue_token("usr_1", ["customer"], now=T0)
        self.assertEqual(verify_token(token, now=T0 + 59 * 60)["sub"], "usr_1")
        with self.assertRaises(AuthError):
            verify_token(token, now=T0 + 60 * 60)

    def test_ttl_follows_config(self):
        with mock.patch.object(config, "TOKEN_TTL_MINUTES", 5):
            token = issue_token("usr_1", now=T0)
        verify_token(token, now=T0 + 4 * 60)
        with self.assertRaises(AuthError):
            verify_token(token, now=T0 + 5 * 60)

    def test_regression_expiry_claim(self):
        token = issue_token("usr_2", ["admin"], now=T0)
        payload = verify_token(token, now=T0 + 1)
        self.assertEqual(payload["exp"] - payload["iat"], 3600)
        self.assertEqual(payload["roles"], ["admin"])


if __name__ == "__main__":
    unittest.main()
