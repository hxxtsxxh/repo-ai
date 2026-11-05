import os
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GUARD = "SHOP_HIDDEN_MAKE_CHILD"


@unittest.skipIf(os.environ.get(GUARD) == "1", "nested run")
class MakeTestTargetTest(unittest.TestCase):
    def test_make_test_runs_the_suite(self):
        make = shutil.which("make")
        self.assertIsNotNone(make, "make is required for this check")
        env = dict(os.environ, **{GUARD: "1"})
        proc = subprocess.run([make, "test", f"PYTHON={sys.executable}"], cwd=ROOT, env=env,
                              capture_output=True, text=True, timeout=120)
        output = proc.stdout + proc.stderr
        self.assertEqual(proc.returncode, 0, output[-2000:])
        match = re.search(r"Ran (\d+) tests?", output)
        self.assertIsNotNone(match, output[-2000:])
        self.assertGreaterEqual(int(match.group(1)), 50, output[-2000:])
        self.assertIn("OK", output)


if __name__ == "__main__":
    unittest.main()
