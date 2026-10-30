"""Licence classification in the skill firewall.

Licences are whole SPDX identifiers and expressions, never substrings:
"SUBMIT" is not MIT, and "MIT + Commons Clause" is not MIT either.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import make_repo, run_cli

from repo_ai import firewall


@pytest.fixture(autouse=True)
def _isolated_quarantine(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("REPO_AI_HOME", str(tmp_path / "rh"))


def _skill(root: Path, license_: str | None, extra: dict[str, str] | None = None,
           name: str = "lic-skill") -> Path:
    d = root / name
    d.mkdir(parents=True)
    front = f"---\nname: {name}\ndescription: \"Summarise a failing test run.\"\n"
    if license_ is not None:
        front += f"license: {license_}\n"
    (d / "SKILL.md").write_text(front + "---\n# Steps\n\n1. Read the output.\n", encoding="utf-8")
    for rel, text in (extra or {}).items():
        (d / rel).write_text(text, encoding="utf-8")
    return d


def _audit(path: Path, **candidate: str) -> firewall.Report:
    dest, files, prior = firewall.quarantine_local(path, path.name)
    cand = {"id": f"local/{path.name}", "name": path.name, "path": path.name, **candidate}
    return firewall.inspect(dest, files, cand, {}, prior)


def _lic_rules(report: firewall.Report) -> list[str]:
    return [f.rule for f in report.findings if f.category == "license"]


# Every example from the audit, plus the standard permissive ones.
@pytest.mark.parametrize("declared, rule", [
    ("BUSL-1.1", "license-restricted"),
    ("SSPL-1.0", "license-restricted"),
    ("CC-BY-NC-SA-4.0", "license-restricted"),
    ("CC-BY-ND-4.0", "license-restricted"),
    ("Elastic-2.0", "license-restricted"),
    ("LicenseRef-Commercial", "license-restricted"),
    ("MIT + Commons Clause", "license-restricted"),
    ("Apache-2.0 WITH Commons-Clause", "license-restricted"),
    ("EUPL-1.2", "copyleft"),
    ("CC-BY-SA-4.0", "copyleft"),
    ("GPL-3.0-or-later", "copyleft"),
    ("GPL-2.0+", "copyleft"),
    ("AGPL-3.0", "copyleft"),
    ("LGPL-2.1-only", "copyleft"),
    ("EPL-2.0", "copyleft"),
    ("MPL-1.1", "copyleft"),
    ("Unknown", "license-unrecognized"),
    ("SUBMIT", "license-unrecognized"),
    ("MIT AND Unknown", "license-unrecognized"),
    ("GPL-2.0 WITH Some-exception", "license-unrecognized"),
    ("(MIT", "license-unrecognized"),
    ("All rights reserved; do not submit", "no-usable-license"),
    ("Proprietary", "no-usable-license"),
    ("UNLICENSED", "no-usable-license"),
    ("NOASSERTION", "no-usable-license"),
])
def test_declared_licence_findings(tmp_path: Path, declared: str, rule: str):
    rep = _audit(_skill(tmp_path, declared))
    assert _lic_rules(rep) == [rule], (declared, rep.license)
    if rule != "copyleft":
        assert rep.verdict != "eligible"
        assert any(f.rule == rule and f.severity == "high" for f in rep.findings)
        assert rule in firewall.LICENSE_GATE_RULES
    else:
        assert next(f for f in rep.findings if f.rule == rule).severity == "medium"


@pytest.mark.parametrize("declared, shown", [
    ("MIT", "MIT"), ("mit", "MIT"), ("Apache-2.0", "APACHE-2.0"), ("BSD-2-Clause", "BSD-2-CLAUSE"),
    ("BSD-3-Clause", "BSD-3-CLAUSE"), ("ISC", "ISC"), ("0BSD", "0BSD"), ("Unlicense", "UNLICENSE"),
    ("BSL-1.0", "BSL-1.0"), ("MPL-2.0", "MPL-2.0"), ("CC-BY-4.0", "CC-BY-4.0"),
    ("MIT License", "MIT"), ("Apache License, Version 2.0", "APACHE-2.0"),
    ("MIT OR Apache-2.0", "MIT OR APACHE-2.0"), ("(MIT OR GPL-3.0)", "(MIT OR GPL-3.0)"),
    ("Apache-2.0 WITH LLVM-exception", "APACHE-2.0 WITH LLVM-EXCEPTION"),
    ("MIT AND BSD-3-Clause", "MIT AND BSD-3-CLAUSE"),
])
def test_permissive_licences_stay_clean(tmp_path: Path, declared: str, shown: str):
    rep = _audit(_skill(tmp_path, declared))
    assert _lic_rules(rep) == [] and rep.verdict == "eligible", (declared, rep.findings)
    assert rep.license == shown


def test_or_takes_the_best_option_and_the_worst():
    assert firewall.license_class("BUSL-1.1 OR MIT") == "permissive"
    assert firewall.license_class("GPL-3.0 OR BUSL-1.1") == "copyleft"
    assert firewall.license_class("MIT AND GPL-3.0") == "copyleft"
    assert firewall.license_class("(MIT OR GPL-3.0) AND BUSL-1.1") == "restricted"
    assert firewall.license_class("MIT AND Unknown") == "unrecognized"


def test_no_substring_matches():
    # "SUBMIT" contains "MIT"; "LicenseRef-..." contains "LICENSE"; BUSL is not BSL.
    for text in ("SUBMIT", "PERMIT", "MITX", "GPL-3.0X", "XMIT-0", "LicenseRef-MIT"):
        assert firewall.license_class(text) != "permissive", text
    assert firewall.license_class("BUSL-1.1") == "restricted"
    assert firewall.license_class("BSL-1.0") == "permissive"


def test_mpl_2_is_permissive_like_before():
    assert "MPL-2.0" in firewall.PERMISSIVE and "MPL-2.0" not in firewall.COPYLEFT
    assert firewall.license_class("MPL-2.0") == "permissive"
    assert firewall.license_class("MPL-2.0-no-copyleft-exception") == "copyleft"


def test_long_declared_text_is_never_cut_into_a_permissive_one(tmp_path: Path):
    # The stored licence string is re-classified; cutting it must not drop the bad part.
    declared = " AND ".join(["MIT"] * 60) + " AND BUSL-1.1"
    rep = _audit(_skill(tmp_path, declared))
    assert rep.verdict != "eligible" and _lic_rules(rep) in (["license-restricted"], ["license-unrecognized"])
    junk = "MIT AND " + "x" * 300
    assert firewall.license_class(firewall._license_display(junk)) == "unrecognized"


# Repository licence (no licence in the skill): existing behaviour is kept.
@pytest.mark.parametrize("repo_license, rule", [
    ("", "no-usable-license"), ("NOASSERTION", "no-usable-license"), ("OTHER", "no-usable-license"),
    ("GPL-3.0", "copyleft"), ("AGPL-3.0", "copyleft"),
    ("BUSL-1.1", "license-restricted"), ("CC-BY-NC-4.0", "license-restricted"),
])
def test_repo_licence(tmp_path: Path, repo_license: str, rule: str):
    rep = _audit(_skill(tmp_path, None), repo_license=repo_license)
    assert _lic_rules(rep) == [rule]


@pytest.mark.parametrize("repo_license", ["MIT", "Apache-2.0", "BSD-3-Clause", "ISC"])
def test_permissive_repo_licence_is_clean(tmp_path: Path, repo_license: str):
    rep = _audit(_skill(tmp_path, None), repo_license=repo_license)
    assert _lic_rules(rep) == [] and rep.verdict == "eligible"


MIT_TEXT = ("MIT License\n\nCopyright (c) 2026 Acme\n\nPermission is hereby granted, free of charge, to any\n"
            "person obtaining a copy of this software...\n")
APACHE_TEXT = "                                 Apache License\n                           Version 2.0, January 2004\n"
BSD3_TEXT = ("Copyright (c) 2026, Acme. All rights reserved.\n\nRedistribution and use in source and binary\n"
             "forms, with or without modification, are permitted...\n3. Neither the name of the copyright\n")
ISC_TEXT = ("ISC License\n\nPermission to use, copy, modify, and/or distribute this software for any\n"
            "purpose with or without fee is hereby granted, provided that...\n")
GPL3_TEXT = "GNU GENERAL PUBLIC LICENSE\nVersion 3, 29 June 2007\n"
LGPL3_TEXT = "GNU LESSER GENERAL PUBLIC LICENSE\nVersion 3, 29 June 2007\n...the GNU General Public License...\n"


@pytest.mark.parametrize("text, spdx", [
    (MIT_TEXT, "MIT"), (APACHE_TEXT, "APACHE-2.0"), (BSD3_TEXT, "BSD-3-CLAUSE"), (ISC_TEXT, "ISC"),
    (GPL3_TEXT, "GPL-3.0"), (LGPL3_TEXT, "LGPL-3.0"),
    ("GNU AFFERO GENERAL PUBLIC LICENSE\nVersion 3\n", "AGPL-3.0"),
    ("Mozilla Public License Version 2.0\n", "MPL-2.0"),
    (MIT_TEXT + "\n\"Commons Clause\" License Condition v1.0\n", "COMMONS-CLAUSE"),
    ("Business Source License 1.1\n", "BUSL-1.1"),
    ("Server Side Public License\nVERSION 1\n", "SSPL-1.0"),
    ("Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International\n", "LICENSEREF-NONCOMMERCIAL"),
    ("Copyright 2026 Acme. All rights reserved.\n", "PROPRIETARY"),
    # 3-letter substrings never count:
    ("Please do not SUBMIT license changes to this file.\n", ""),
    ("We admit no liability.\n", ""),
    ("Some custom terms.\n", ""),
])
def test_detect_license_text(text: str, spdx: str):
    assert firewall._detect_license(text) == spdx


@pytest.mark.parametrize("text, rule", [
    (MIT_TEXT, None), (APACHE_TEXT, None), (BSD3_TEXT, None), (ISC_TEXT, None),
    (GPL3_TEXT, "copyleft"),
    (MIT_TEXT + "\nCommons Clause License Condition v1.0\n", "license-restricted"),
    ("Copyright 2026 Acme. All rights reserved.\n", "no-usable-license"),
    ("Please do not submit pull requests.\n", "license-unrecognized"),
])
def test_licence_file_without_declared_licence(tmp_path: Path, text: str, rule: str | None):
    # A skill's own LICENSE file decides, even when the repository says MIT.
    rep = _audit(_skill(tmp_path, None, {"LICENSE": text}), repo_license="MIT")
    assert _lic_rules(rep) == ([rule] if rule else [])


def test_declared_reference_to_licence_file(tmp_path: Path):
    rep = _audit(_skill(tmp_path, "Complete terms in LICENSE.txt", {"LICENSE.txt": APACHE_TEXT}))
    assert rep.license == "APACHE-2.0" and _lic_rules(rep) == []
    # A LicenseRef is not a reference to the LICENSE file.
    rep = _audit(_skill(tmp_path / "b", "LicenseRef-Commercial", {"LICENSE": MIT_TEXT}))
    assert _lic_rules(rep) == ["license-restricted"]
    # Restrictive words in the declaration win over a permissive file.
    rep = _audit(_skill(tmp_path / "c", "Proprietary. LICENSE.txt has complete terms",
                        {"LICENSE.txt": MIT_TEXT}))
    assert _lic_rules(rep) == ["no-usable-license"]


def _discover_and_install(tmp_path: Path, home: dict[str, str], declared: str | None):
    repo = make_repo(tmp_path, "pyweb")
    assert run_cli(repo, "init", "--agent", "claude", "-q", env=home).returncode == 0
    src = _skill(tmp_path / "incoming", declared, name="gated")
    data = json.loads(run_cli(repo, "skills", "discover", "--from-path", str(src), "--json", env=home).stdout)
    rep = next(iter(data["reports"].values()))
    proc = run_cli(repo, "skills", "install", "gated", "--approve", rep["content_hash"][:16],
                   "--accept-review", env=home)
    return rep, proc


def test_no_usable_license_still_blocks_install(tmp_path: Path):
    home = {"REPO_AI_HOME": str(tmp_path / "rh"), "REPO_AI_NO_BACKGROUND": "1"}
    rep, proc = _discover_and_install(tmp_path, home, "All rights reserved; do not submit")
    assert any(f["rule"] == "no-usable-license" for f in rep["findings"])
    assert proc.returncode != 0 and "licence" in proc.stderr


@pytest.mark.parametrize("declared", ["BUSL-1.1", "Unknown"])
def test_restricted_and_unrecognised_block_install(tmp_path: Path, declared: str):
    home = {"REPO_AI_HOME": str(tmp_path / "rh"), "REPO_AI_NO_BACKGROUND": "1"}
    rep, proc = _discover_and_install(tmp_path, home, declared)
    assert any(f["rule"] in firewall.LICENSE_GATE_RULES for f in rep["findings"])
    assert proc.returncode != 0 and "licence" in proc.stderr
