import unittest
from decimal import Decimal

from shop.utils.money import allocate, apply_basis_points, apply_percent, format_money, from_cents, to_cents


class ToCentsTest(unittest.TestCase):
    def test_parses_strings(self):
        self.assertEqual(to_cents("12.34"), 1234)
        self.assertEqual(to_cents(" 7 "), 700)

    def test_rounds_half_up(self):
        self.assertEqual(to_cents("0.005"), 1)

    def test_rejects_garbage(self):
        with self.assertRaises(ValueError):
            to_cents("twelve")


class FormatMoneyTest(unittest.TestCase):
    def test_usd(self):
        self.assertEqual(format_money(123456), "$1,234.56")

    def test_negative(self):
        self.assertEqual(format_money(-500), "-$5.00")

    def test_other_currency(self):
        self.assertEqual(format_money(100, "GBP"), "£1.00")

    def test_from_cents(self):
        self.assertEqual(from_cents(1999), Decimal("19.99"))


class PercentTest(unittest.TestCase):
    def test_round_numbers(self):
        self.assertEqual(apply_percent(1000, 10), 100)
        self.assertEqual(apply_percent(2000, 15), 300)

    def test_basis_points(self):
        self.assertEqual(apply_basis_points(10000, 725), 725)


class AllocateTest(unittest.TestCase):
    def test_sums_to_total(self):
        parts = allocate(1000, [1, 1, 1])
        self.assertEqual(sum(parts), 1000)
        self.assertEqual(parts, [334, 333, 333])


if __name__ == "__main__":
    unittest.main()
