import hashlib
import unittest
from unittest import mock

from shop import config
from shop.app import create_app
from shop.errors import AuthError
from shop.services.auth import hash_password, verify_password


def legacy_hash(password, salt="0011aabb", iterations=20_000):
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), iterations)
    return f"pbkdf2${iterations}${salt}${digest.hex()}"


class ScryptHashTest(unittest.TestCase):
    def test_new_hashes_use_scrypt(self):
        stored = hash_password("correct horse battery")
        parts = stored.split("$")
        self.assertEqual(parts[0], "scrypt")
        self.assertEqual(parts[1:4], ["16384", "8", "1"])
        self.assertEqual(len(parts), 6)
        self.assertEqual(len(parts[5]), 128)
        self.assertTrue(verify_password("correct horse battery", stored))
        self.assertFalse(verify_password("correct horse", stored))

    def test_digest_is_standard_scrypt(self):
        stored = hash_password("pw-123456", salt="feedface")
        expected = hashlib.scrypt(b"pw-123456", salt=b"feedface", n=2**14, r=8, p=1, dklen=64).hex()
        self.assertEqual(stored, f"scrypt$16384$8$1$feedface${expected}")

    def test_salts_are_random(self):
        self.assertNotEqual(hash_password("same-password"), hash_password("same-password"))

    def test_parameters_are_read_from_the_hash(self):
        with mock.patch.object(config, "SCRYPT_N", 2**10):
            cheap = hash_password("pw-abcdefg")
        self.assertTrue(cheap.startswith("scrypt$1024$8$1$"))
        self.assertTrue(verify_password("pw-abcdefg", cheap))

    def test_legacy_hashes_still_verify(self):
        self.assertTrue(verify_password("old-password", legacy_hash("old-password")))
        self.assertTrue(verify_password("old-password", legacy_hash("old-password", iterations=1000)))
        self.assertFalse(verify_password("wrong", legacy_hash("old-password")))

    def test_garbage_does_not_verify(self):
        for stored in ("", "plain", "md5$abc", "scrypt$x$8$1$aa$bb", "pbkdf2$abc$def", "scrypt$16384$8$1$aa"):
            self.assertFalse(verify_password("anything", stored), stored)


class RehashOnLoginTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.ctx = self.app.ctx
        user = self.ctx.user_service.register("old@example.com", "Old", "placeholder-pass")
        user.password_hash = legacy_hash("old-password")
        self.ctx.users.update(user)
        self.user_id = user.id

    def stored(self):
        return self.ctx.users.get(self.user_id).password_hash

    def test_successful_login_upgrades_hash(self):
        resp = self.app.request("POST", "/auth/login", body={"email": "old@example.com", "password": "old-password"})
        self.assertEqual(resp["status"], 200)
        self.assertTrue(self.stored().startswith("scrypt$16384$8$1$"))
        self.assertTrue(verify_password("old-password", self.stored()))
        resp = self.app.request("POST", "/auth/login", body={"email": "old@example.com", "password": "old-password"})
        self.assertEqual(resp["status"], 200)

    def test_failed_login_keeps_legacy_hash(self):
        before = self.stored()
        with self.assertRaises(AuthError):
            self.ctx.user_service.authenticate("old@example.com", "nope-nope")
        self.assertEqual(self.stored(), before)

    def test_new_registrations_and_login(self):
        headers = self.app.register_and_login("new@example.com", "brand-new-pass")
        self.assertEqual(self.app.request("GET", "/users/me", headers=headers)["status"], 200)
        stored = self.ctx.users.by_email("new@example.com").password_hash
        self.assertTrue(stored.startswith("scrypt$"))


if __name__ == "__main__":
    unittest.main()
