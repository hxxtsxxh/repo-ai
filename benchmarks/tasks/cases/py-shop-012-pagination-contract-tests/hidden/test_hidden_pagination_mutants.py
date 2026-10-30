"""Checks that the repository's own tests detect broken pagination implementations."""

import importlib
import io
import pathlib
import sys
import unittest

HERE = pathlib.Path(__file__).resolve().parent
SELF = pathlib.Path(__file__).stem


def _purge():
    for name in list(sys.modules):
        if name == "shop" or name.startswith("shop."):
            del sys.modules[name]
        elif name.startswith("tests.") and name != f"tests.{SELF}":
            del sys.modules[name]


def _floor_pages(mod):
    def paginate(items, page=1, per_page=None):
        items = list(items)
        per_page = mod.clamp_per_page(per_page)
        page = max(1, int(page or 1))
        total = len(items)
        pages = total // per_page
        if pages and page > pages:
            return mod.Page(items=[], page=page, per_page=per_page, total=total, pages=pages)
        start = (page - 1) * per_page
        return mod.Page(items=items[start:start + per_page], page=page, per_page=per_page,
                        total=total, pages=pages)
    return {"paginate": paginate}


def _no_max(mod):
    def clamp_per_page(per_page):
        if per_page is None:
            return mod.config.DEFAULT_PAGE_SIZE
        return max(1, int(per_page))
    return {"clamp_per_page": clamp_per_page}


def _no_min(mod):
    def clamp_per_page(per_page):
        if per_page is None:
            return mod.config.DEFAULT_PAGE_SIZE
        return min(abs(int(per_page)) or mod.config.DEFAULT_PAGE_SIZE, mod.config.MAX_PAGE_SIZE)
    return {"clamp_per_page": clamp_per_page}


def _past_end_repeats_last(mod):
    original = mod.paginate

    def paginate(items, page=1, per_page=None):
        items = list(items)
        result = original(items, page, per_page)
        if not result.items and result.pages:
            return original(items, result.pages, per_page)
        return result
    return {"paginate": paginate}


def _run_suite(mutant=None):
    _purge()
    mod = importlib.import_module("shop.utils.pagination")
    if mutant is not None:
        for name, fn in mutant(mod).items():
            setattr(mod, name, fn)
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for path in sorted(HERE.glob("test_*.py")):
        if path.stem == SELF or path.stem.startswith("test_hidden"):
            continue
        suite.addTests(loader.loadTestsFromName(f"tests.{path.stem}"))
    result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite)
    _purge()
    return result


class PaginationTestsCatchRegressions(unittest.TestCase):
    def test_suite_passes_on_real_implementation(self):
        result = _run_suite()
        self.assertTrue(result.wasSuccessful(), [str(f[0]) for f in result.failures + result.errors])
        self.assertGreater(result.testsRun, 50)

    def test_detects_floor_division_page_count(self):
        self.assertFalse(_run_suite(_floor_pages).wasSuccessful(), "partial last page not covered")

    def test_detects_missing_max_clamp(self):
        self.assertFalse(_run_suite(_no_max).wasSuccessful(), "per_page upper bound not covered")

    def test_detects_missing_min_clamp(self):
        self.assertFalse(_run_suite(_no_min).wasSuccessful(), "per_page lower bound not covered")

    def test_detects_page_past_end(self):
        self.assertFalse(_run_suite(_past_end_repeats_last).wasSuccessful(), "page past the end not covered")


if __name__ == "__main__":
    unittest.main()
