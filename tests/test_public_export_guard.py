"""scripts/public_export.py keeps forbidden identifiers only as digests and still finds them."""
from __future__ import annotations

import hashlib
import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _module():
    spec = importlib.util.spec_from_file_location("public_export", ROOT / "scripts" / "public_export.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_the_guard_file_names_no_corporate_identifier():
    text = (ROOT / "scripts" / "public_export.py").read_text().lower()
    assert "@ib" + "m" not in text and "ib" + "m." not in text and "ib" + "m confidential" not in text


def test_a_listed_address_is_found_by_its_digest_case_insensitively():
    mod = _module()
    rules = [(re.compile(rb"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "address",
              {hashlib.sha256(b"someone@example.org").hexdigest()})]
    assert mod.digest_hits(b"contact: Someone@Example.org today", rules) == ["address"]
    assert mod.digest_hits(b"contact: other@example.org", rules) == []


def test_the_real_rules_are_digests_only():
    mod = _module()
    for _pattern, _what, digests in mod.FORBIDDEN_DIGESTS:
        assert digests and all(re.fullmatch(r"[0-9a-f]{64}", d) for d in digests)
