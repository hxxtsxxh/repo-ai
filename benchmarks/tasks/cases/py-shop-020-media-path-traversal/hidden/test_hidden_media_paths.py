import os
import shutil
import tempfile
import unittest
from unittest import mock

from shop import config
from shop.app import create_app


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(data)


class MediaContainmentTest(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.base, True)
        self.root = os.path.join(self.base, "media")
        _write(os.path.join(self.root, "tee.txt"), b"tee photo")
        _write(os.path.join(self.root, "thumbs", "tee.txt"), b"tee thumb")
        _write(os.path.join(self.base, "media-backups", "customers.csv"), b"SECRET customers")
        _write(os.path.join(self.base, "mediaprivate.txt"), b"SECRET flat")
        _write(os.path.join(self.base, "settings.txt"), b"SECRET settings")
        patcher = mock.patch.object(config, "MEDIA_ROOT", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.app = create_app()

    def get(self, name):
        return self.app.request("GET", f"/media/{name}")

    def assertBlocked(self, name):
        resp = self.get(name)
        self.assertIn(resp["status"], (400, 403, 404), name)
        self.assertNotIn(b"SECRET", resp["body"] if isinstance(resp["body"], bytes) else b"", name)

    def test_files_inside_root_are_served(self):
        resp = self.get("tee.txt")
        self.assertEqual(resp["status"], 200)
        self.assertEqual(resp["body"], b"tee photo")
        resp = self.get("thumbs%2Ftee.txt")
        self.assertEqual(resp["status"], 200)
        self.assertEqual(resp["body"], b"tee thumb")

    def test_sibling_directory_sharing_the_prefix_is_blocked(self):
        self.assertBlocked("..%2Fmedia-backups%2Fcustomers.csv")
        self.assertBlocked("..%2Fmedia%2F..%2Fmedia-backups%2Fcustomers.csv")
        self.assertBlocked("thumbs%2F..%2F..%2Fmedia-backups%2Fcustomers.csv")
        self.assertBlocked("..%2Fmediaprivate.txt")

    def test_classic_traversal_is_blocked(self):
        self.assertBlocked("..%2Fsettings.txt")
        self.assertBlocked("..%2F..%2F..%2F..%2F..%2F..%2Fetc%2Fhosts")
        self.assertBlocked("%2Fetc%2Fhosts")

    def test_trailing_separator_in_setting(self):
        with mock.patch.object(config, "MEDIA_ROOT", self.root + os.sep):
            self.assertEqual(self.get("tee.txt")["status"], 200)
            self.assertBlocked("..%2Fmedia-backups%2Fcustomers.csv")

    def test_missing_file_is_404(self):
        self.assertEqual(self.get("nope.png")["status"], 404)


if __name__ == "__main__":
    unittest.main()
