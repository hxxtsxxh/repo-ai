import unittest

from shop.utils.slugify import slugify, unique_slug


class SlugifyTest(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(slugify("Logo Tee"), "logo-tee")

    def test_punctuation(self):
        self.assertEqual(slugify("  Hello, World!  "), "hello-world")

    def test_unique(self):
        self.assertEqual(unique_slug("Logo Tee", {"logo-tee"}), "logo-tee-2")
        self.assertEqual(unique_slug("Logo Tee", {"logo-tee", "logo-tee-2"}), "logo-tee-3")


if __name__ == "__main__":
    unittest.main()
