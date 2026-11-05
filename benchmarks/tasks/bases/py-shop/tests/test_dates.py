import unittest
from datetime import date

from shop.utils.dates import add_business_days, format_date, is_business_day, parse_iso_date


class DatesTest(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(parse_iso_date("2026-03-02"), date(2026, 3, 2))
        with self.assertRaises(ValueError):
            parse_iso_date("03/02/2026")

    def test_business_day(self):
        self.assertTrue(is_business_day(date(2026, 3, 2)))  # Monday
        self.assertFalse(is_business_day(date(2026, 3, 8)))  # Sunday

    def test_add_within_week(self):
        self.assertEqual(add_business_days(date(2026, 3, 2), 1), date(2026, 3, 3))
        self.assertEqual(add_business_days(date(2026, 3, 2), 3), date(2026, 3, 5))

    def test_format(self):
        self.assertEqual(format_date(date(2026, 3, 4)), "Wed, Mar 04 2026")


if __name__ == "__main__":
    unittest.main()
