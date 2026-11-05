#!/usr/bin/env python3
"""Generate and check the website's release/evidence facts.

The site renders release facts (distribution name, version, install command, PyPI state) and the
Evidence Lab from one generated file, ``site/src/data/release-facts.json``. This script builds it
from validated inputs only:

* ``pyproject.toml``: the distribution name;
* ``src/repo_ai/__init__.py``: the package version;
* the latest final release tag ``vX.Y.Z`` in git (when the clone has tags);
* ``docs/engineering/evidence-matrix.json``: the evidence ledger, including the *verified read*
  of PyPI. PyPI is reported as published only when that verified read exists and names this
  distribution, with a recorded sha256 and date; it is never inferred.

It also validates ``site/src/data/providers.json`` (the provider compatibility matrix).

Usage::

    python scripts/site_facts.py            # (re)write site/src/data/release-facts.json
    python scripts/site_facts.py --check    # exit 1 if the committed file is stale or an input is invalid
    python scripts/site_facts.py --record-pypi   # NETWORK: read PyPI, re-hash the wheel, record it

``--check`` and the default mode never touch the network.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - Python 3.10
    import tomli as tomllib

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
VERSION_FILE = ROOT / "src" / "repo_ai" / "__init__.py"
MATRIX = ROOT / "docs" / "engineering" / "evidence-matrix.json"
PROVIDERS = ROOT / "site" / "src" / "data" / "providers.json"
OUTPUT = ROOT / "site" / "src" / "data" / "release-facts.json"

MATRIX_SCHEMA = "repo-ai.evidence-matrix/1"
PROVIDERS_SCHEMA = "repo-ai.providers/1"
OUTPUT_SCHEMA = "repo-ai.site-release-facts/1"

EVIDENCE_STATUSES = (
    "DEMONSTRATED",
    "EXPERIMENTAL",
    "NOT_YET_DEMONSTRATED",
    "NEGATIVE_RESULT",
    "INCONCLUSIVE",
    "BLOCKED",
    "UNSUPPORTED",
)
PROVIDER_LABELS = ("EXECUTION", "HOST_ONLY", "CONTEXT_SKILLS_ONLY", "PLANNED", "BLOCKED", "UNSUPPORTED")
EXECUTION_STATUSES = ("EXECUTION", "BLOCKED", "PLANNED", "UNSUPPORTED")

ENTRY_REQUIRED = ("id", "title", "status", "stat", "result", "date", "sample_size", "method", "source")
DATE_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])(-(0[1-9]|[12]\d|3[01]))?$")
TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2})?Z)?$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
FINAL_TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


class FactsError(Exception):
    """An input is invalid; the message says which and why."""


# ---------------------------------------------------------------- inputs


def read_distribution(pyproject: Path = PYPROJECT) -> dict[str, str]:
    with pyproject.open("rb") as fh:
        project = tomllib.load(fh)["project"]
    scripts = project.get("scripts", {})
    command = next(iter(scripts), "repo-ai")
    return {
        "distribution": project["name"],
        "command": command,
        "requires_python": project.get("requires-python", ""),
    }


def read_version(version_file: Path = VERSION_FILE) -> str:
    m = re.search(r'^__version__\s*=\s*"([^"]+)"', version_file.read_text(encoding="utf-8"), re.M)
    if not m:
        raise FactsError(f"{version_file}: no __version__ assignment")
    return m.group(1)


def latest_release_tag(root: Path = ROOT) -> str | None:
    """Newest final ``vX.Y.Z`` tag, or None when the clone carries no tags (shallow CI checkouts)."""
    try:
        out = subprocess.run(
            ["git", "tag", "--list", "v*"], cwd=root, capture_output=True, text=True, check=True, timeout=30
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    tags = []
    for line in out.splitlines():
        m = FINAL_TAG_RE.match(line.strip())
        if m:
            tags.append((tuple(int(x) for x in m.groups()), line.strip()))
    return max(tags)[1] if tags else None


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FactsError(f"{path.relative_to(ROOT)}: missing") from exc
    except json.JSONDecodeError as exc:
        raise FactsError(f"{path.relative_to(ROOT)}: invalid JSON ({exc})") from exc


# ---------------------------------------------------------------- validation


def _source_exists(source: str, root: Path) -> bool:
    path = source.split("#", 1)[0]
    return bool(path) and not path.startswith(("/", "..")) and (root / path).is_file()


def validate_matrix(matrix: dict[str, Any], root: Path = ROOT) -> list[str]:
    """Return a list of problems (empty when the matrix is valid)."""
    problems: list[str] = []
    if matrix.get("schema") != MATRIX_SCHEMA:
        problems.append(f"evidence matrix: schema must be {MATRIX_SCHEMA!r}")
    if not DATE_RE.match(str(matrix.get("updated", ""))):
        problems.append("evidence matrix: 'updated' must be YYYY-MM-DD")
    statuses = matrix.get("statuses", {})
    if tuple(statuses) != EVIDENCE_STATUSES:
        problems.append(f"evidence matrix: 'statuses' must define exactly {', '.join(EVIDENCE_STATUSES)} in that order")
    seen: set[str] = set()
    entries = matrix.get("entries")
    if not isinstance(entries, list) or not entries:
        problems.append("evidence matrix: 'entries' must be a non-empty list")
        entries = []
    for i, entry in enumerate(entries):
        where = f"evidence entry {entry.get('id', i)!r}"
        for key in ENTRY_REQUIRED:
            if not isinstance(entry.get(key), str) or not entry[key].strip():
                problems.append(f"{where}: '{key}' is required (non-empty string)")
        eid = entry.get("id", "")
        if eid and not ID_RE.match(eid):
            problems.append(f"{where}: id must be lowercase letters, digits and hyphens")
        if eid in seen:
            problems.append(f"{where}: duplicate id")
        seen.add(eid)
        if entry.get("status") and entry["status"] not in EVIDENCE_STATUSES:
            problems.append(f"{where}: unknown status {entry['status']!r}")
        if entry.get("date") and not DATE_RE.match(entry["date"]):
            problems.append(f"{where}: date must be YYYY-MM-DD or YYYY-MM")
        if entry.get("source") and not _source_exists(entry["source"], root):
            problems.append(f"{where}: source {entry['source']!r} is not a file in the repository")
        if "featured" in entry and not isinstance(entry["featured"], bool):
            problems.append(f"{where}: 'featured' must be true or false")
    problems += validate_pypi_read(matrix)
    return problems


def validate_pypi_read(matrix: dict[str, Any]) -> list[str]:
    pypi = matrix.get("distribution", {}).get("pypi", {})
    if "published" in pypi:
        return ["evidence matrix: distribution.pypi must not carry 'published'; it is derived from verified_read"]
    read = pypi.get("verified_read")
    if read is None:
        return []
    problems = []
    for key in ("distribution", "version", "verified_at", "method", "url", "wheel", "wheel_sha256"):
        if not isinstance(read.get(key), str) or not read[key].strip():
            problems.append(f"pypi verified_read: '{key}' is required")
    if read.get("verified_at") and not TIMESTAMP_RE.match(read["verified_at"]):
        problems.append("pypi verified_read: verified_at must be YYYY-MM-DD or YYYY-MM-DDTHH:MM[:SS]Z")
    for key in ("wheel_sha256", "sdist_sha256"):
        if key in read and not SHA256_RE.match(str(read[key])):
            problems.append(f"pypi verified_read: {key} must be 64 lowercase hex characters")
    return problems


def validate_providers(data: dict[str, Any], root: Path = ROOT) -> list[str]:
    problems: list[str] = []
    if data.get("schema") != PROVIDERS_SCHEMA:
        problems.append(f"providers: schema must be {PROVIDERS_SCHEMA!r}")
    if not DATE_RE.match(str(data.get("as_of", ""))):
        problems.append("providers: 'as_of' must be YYYY-MM-DD")
    if tuple(data.get("labels", {})) != PROVIDER_LABELS:
        problems.append(f"providers: 'labels' must define exactly {', '.join(PROVIDER_LABELS)} in that order")
    seen: set[str] = set()
    for i, prov in enumerate(data.get("providers") or []):
        where = f"provider {prov.get('id', i)!r}"
        for key in ("id", "name", "agent", "label", "host", "cost"):
            if not isinstance(prov.get(key), str) or not prov[key].strip():
                problems.append(f"{where}: '{key}' is required")
        if prov.get("id") in seen:
            problems.append(f"{where}: duplicate id")
        seen.add(prov.get("id"))
        if prov.get("label") not in PROVIDER_LABELS:
            problems.append(f"{where}: unknown label {prov.get('label')!r}")
        ex = prov.get("execution") or {}
        for key in ("status", "observed", "verified_on", "version", "sample", "platforms", "source"):
            if not isinstance(ex.get(key), str) or not ex[key].strip():
                problems.append(f"{where}: execution.{key} is required")
        if ex.get("status") and ex["status"] not in EXECUTION_STATUSES:
            problems.append(f"{where}: execution.status must be one of {', '.join(EXECUTION_STATUSES)}")
        if ex.get("verified_on") and not DATE_RE.match(ex["verified_on"]):
            problems.append(f"{where}: execution.verified_on must be YYYY-MM-DD or YYYY-MM")
        if ex.get("source") and not _source_exists(ex["source"], root):
            problems.append(f"{where}: execution.source {ex['source']!r} is not a file in the repository")
        if (prov.get("label") == "EXECUTION") != (ex.get("status") == "EXECUTION"):
            problems.append(f"{where}: label EXECUTION and execution.status EXECUTION must go together")
    if not seen:
        problems.append("providers: 'providers' must be a non-empty list")
    return problems


# ---------------------------------------------------------------- build


def pypi_facts(matrix: dict[str, Any], distribution: str, tag: str | None) -> tuple[dict[str, Any], list[str]]:
    """PyPI state for the site. Published only from a matching verified read."""
    read = matrix.get("distribution", {}).get("pypi", {}).get("verified_read")
    problems: list[str] = []
    if not read:
        return {"published": False, "reason": "no verified read recorded"}, problems
    if read.get("distribution") != distribution:
        problems.append(
            f"pypi verified_read names {read.get('distribution')!r}, but pyproject.toml's distribution is {distribution!r}"
        )
        return {"published": False, "reason": "verified read is for another distribution"}, problems
    if tag is not None and f"v{read['version']}" != tag:
        problems.append(f"pypi verified_read is for {read['version']}, but the latest release tag is {tag}")
    facts = {
        "published": True,
        "distribution": read["distribution"],
        "version": read["version"],
        "url": read["url"],
        "verified_at": read["verified_at"],
        "wheel": read["wheel"],
        "wheel_sha256": read["wheel_sha256"],
    }
    if "sdist_sha256" in read:
        facts["sdist_sha256"] = read["sdist_sha256"]
    return facts, problems


def build_facts(
    *,
    matrix: dict[str, Any],
    providers: dict[str, Any],
    dist: dict[str, str],
    version: str,
    tag: str | None,
    root: Path = ROOT,
) -> tuple[dict[str, Any], list[str]]:
    problems = validate_matrix(matrix, root) + validate_providers(providers, root)
    pypi, pypi_problems = pypi_facts(matrix, dist["distribution"], tag)
    problems += pypi_problems
    repo = matrix.get("distribution", {}).get("repository", {})
    repo_url = repo.get("url", "")
    # The version the site describes: the verified PyPI release when there is one, else the source version.
    site_version = pypi["version"] if pypi["published"] else version
    facts = {
        "schema": OUTPUT_SCHEMA,
        "generated_by": "scripts/site_facts.py",
        "note": "Generated; do not edit. Change the inputs and run `python scripts/site_facts.py`.",
        "facts_as_of": matrix.get("updated"),
        "package": {"version": version, **dist},
        "site_version": site_version,
        "release": {
            "tag": tag,
            "url": f"{repo_url}/releases/tag/{tag}" if tag and repo_url else None,
        },
        "repository": {
            "url": repo_url,
            "public": repo.get("public") is True and bool(repo.get("verified_at")),
            "verified_at": repo.get("verified_at"),
        },
        "pypi": pypi,
        "evidence": {
            "updated": matrix.get("updated"),
            "statuses": matrix.get("statuses"),
            "entries": [
                {**e, "source_url": f"{repo_url}/blob/main/{e['source']}" if repo_url else None}
                for e in matrix.get("entries", [])
            ],
        },
    }
    return facts, problems


def current_facts(root: Path = ROOT, tag_override: str | None = None) -> tuple[dict[str, Any], list[str], bool]:
    """Build facts from the repository. Returns (facts, problems, tag_known)."""
    matrix = load_json(root / MATRIX.relative_to(ROOT))
    providers = load_json(root / PROVIDERS.relative_to(ROOT))
    tag = tag_override if tag_override is not None else latest_release_tag(root)
    facts, problems = build_facts(
        matrix=matrix,
        providers=providers,
        dist=read_distribution(root / PYPROJECT.relative_to(ROOT)),
        version=read_version(root / VERSION_FILE.relative_to(ROOT)),
        tag=tag,
        root=root,
    )
    return facts, problems, tag is not None


def render(facts: dict[str, Any]) -> str:
    return json.dumps(facts, indent=2, ensure_ascii=False) + "\n"


# ---------------------------------------------------------------- network (explicit only)


def record_pypi(matrix_path: Path = MATRIX) -> dict[str, Any]:
    """Read PyPI for this distribution/version, re-hash the wheel, and write the verified read."""
    dist = read_distribution()["distribution"]
    version = read_version()
    url = f"https://pypi.org/pypi/{dist}/{version}/json"
    with urllib.request.urlopen(url, timeout=60) as resp:  # noqa: S310 - fixed https URL
        meta = json.load(resp)
    files = {f["packagetype"]: f for f in meta["urls"]}
    wheel = files.get("bdist_wheel")
    if not wheel:
        raise FactsError(f"{url}: no wheel listed")
    with urllib.request.urlopen(wheel["url"], timeout=120) as resp:  # noqa: S310 - PyPI file URL
        digest = hashlib.sha256(resp.read()).hexdigest()
    if digest != wheel["digests"]["sha256"]:
        raise FactsError(f"wheel sha256 {digest} does not match PyPI's digest {wheel['digests']['sha256']}")
    read = {
        "distribution": meta["info"]["name"],
        "version": meta["info"]["version"],
        "url": f"https://pypi.org/project/{dist}/{version}/",
        "verified_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "method": f"GET {url}; downloaded the wheel and recomputed its sha256, which matched PyPI's digest",
        "wheel": wheel["filename"],
        "wheel_sha256": digest,
    }
    if "sdist" in files:
        read["sdist"] = files["sdist"]["filename"]
        read["sdist_sha256"] = files["sdist"]["digests"]["sha256"]
    matrix = load_json(matrix_path)
    matrix.setdefault("distribution", {}).setdefault("pypi", {})["verified_read"] = read
    matrix_path.write_text(json.dumps(matrix, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return read


# ---------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="fail if the committed facts are stale or an input is invalid")
    mode.add_argument("--record-pypi", action="store_true", help="NETWORK: verify PyPI and record the read, then regenerate")
    args = ap.parse_args(argv)

    if args.record_pypi:
        read = record_pypi()
        print(f"recorded PyPI verified read: {read['distribution']} {read['version']} wheel {read['wheel_sha256']}")

    committed_text = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else None
    committed = json.loads(committed_text) if committed_text else None
    tag_override = None
    facts, problems, tag_known = current_facts()
    if not tag_known and committed is not None:
        # Shallow clone without tags: the tag cannot be checked here, so keep the committed one.
        tag_override = committed.get("release", {}).get("tag")
        facts, problems, _ = current_facts(tag_override=tag_override)
        print(f"site_facts: no release tags in this clone; tag {tag_override!r} taken from the committed file, not verified",
              file=sys.stderr)

    if problems:
        for p in problems:
            print(f"site_facts: {p}", file=sys.stderr)
        return 1

    if facts["package"]["version"] != facts["site_version"]:
        print(
            f"site_facts: note: source version {facts['package']['version']} differs from the published "
            f"{facts['site_version']} the site describes",
            file=sys.stderr,
        )

    if args.check:
        if committed != facts:
            print(
                f"site_facts: {OUTPUT.relative_to(ROOT)} is stale; run `python scripts/site_facts.py` and commit it",
                file=sys.stderr,
            )
            return 1
        print(f"site_facts: {OUTPUT.relative_to(ROOT)} is current")
        return 0

    OUTPUT.write_text(render(facts), encoding="utf-8", newline="\n")
    print(f"site_facts: wrote {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
