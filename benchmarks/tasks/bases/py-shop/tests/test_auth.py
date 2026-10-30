import unittest

from shop.errors import AuthError
from shop.services.auth import hash_password, issue_token, verify_password, verify_token


class AuthTest(unittest.TestCase):
    def test_password_roundtrip(self):
        stored = hash_password("correct horse", salt="abc")
        self.assertTrue(verify_password("correct horse", stored))
        self.assertFalse(verify_password("wrong", stored))

    def test_token_roundtrip(self):
        token = issue_token("usr_0001", ["customer"], now=1_000_000)
        payload = verify_token(token, now=1_000_010)
        self.assertEqual(payload["sub"], "usr_0001")
        self.assertEqual(payload["roles"], ["customer"])

    def test_garbage_token(self):
        with self.assertRaises(AuthError):
            verify_token("not-a-token")


if __name__ == "__main__":
    unittest.main()
