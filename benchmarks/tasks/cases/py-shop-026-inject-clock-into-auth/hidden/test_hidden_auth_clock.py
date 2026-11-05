import unittest
from datetime import datetime, timedelta, timezone

from shop import config
from shop.app import create_app
from shop.services.auth import issue_token, verify_token


class FakeClock:
    def __init__(self, start):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, **kwargs):
        self.now += timedelta(**kwargs)


def token_of(headers):
    return headers["Authorization"].split(" ", 1)[1]


class AuthClockTest(unittest.TestCase):
    def test_login_uses_app_clock(self):
        clock = FakeClock(datetime(2031, 5, 4, 9, 0, tzinfo=timezone.utc))
        app = create_app(clock=clock)
        headers = app.register_and_login("ada@example.com")
        payload = verify_token(token_of(headers), now=clock().timestamp())
        self.assertEqual(payload["iat"], int(clock().timestamp()))
        self.assertEqual(payload["exp"] - payload["iat"], config.TOKEN_TTL_MINUTES * 60)

    def test_expiry_follows_fake_clock(self):
        clock = FakeClock(datetime(2031, 5, 4, 9, 0, tzinfo=timezone.utc))
        app = create_app(clock=clock)
        headers = app.register_and_login("ada@example.com")
        self.assertEqual(app.request("GET", "/users/me", headers=headers)["status"], 200)
        clock.advance(minutes=config.TOKEN_TTL_MINUTES - 1)
        self.assertEqual(app.request("GET", "/orders", headers=headers)["status"], 200)
        clock.advance(minutes=2)
        resp = app.request("GET", "/users/me", headers=headers)
        self.assertEqual(resp["status"], 401)
        self.assertIn("expired", resp["body"]["error"]["message"])
        fresh = app.login("ada@example.com", "customer-pass-1")
        self.assertEqual(app.request("GET", "/users/me", headers=fresh)["status"], 200)

    def test_clock_in_the_past(self):
        clock = FakeClock(datetime(2020, 1, 1, 12, 0, tzinfo=timezone.utc))
        app = create_app(clock=clock)
        headers = app.register_and_login("bob@example.com")
        self.assertEqual(app.request("GET", "/users/me", headers=headers)["status"], 200)

    def test_direct_now_still_supported(self):
        token = issue_token("usr_0042", ["customer"], now=1_000_000)
        self.assertEqual(verify_token(token, now=1_000_000 + 60)["sub"], "usr_0042")

    def test_default_app_still_works(self):
        app = create_app()
        headers = app.register_and_login("cy@example.com")
        self.assertEqual(app.request("GET", "/users/me", headers=headers)["status"], 200)


if __name__ == "__main__":
    unittest.main()
