import unittest

from shop.errors import ValidationError
from shop.utils.validation import is_valid_email, require_fields, validate_quantity, validate_sku


class ValidationTest(unittest.TestCase):
    def test_email(self):
        self.assertTrue(is_valid_email("ada@example.com"))
        self.assertFalse(is_valid_email("not-an-email"))
        self.assertFalse(is_valid_email("a@b"))

    def test_sku(self):
        self.assertEqual(validate_sku("tee-0001"), "TEE-0001")
        with self.assertRaises(ValidationError):
            validate_sku("T-1")

    def test_quantity(self):
        self.assertEqual(validate_quantity("3"), 3)
        with self.assertRaises(ValidationError):
            validate_quantity(0)

    def test_require_fields(self):
        with self.assertRaises(ValidationError):
            require_fields({"a": 1}, "a", "b")


if __name__ == "__main__":
    unittest.main()
