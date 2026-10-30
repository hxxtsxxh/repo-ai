"""A pinned claim: what is supposed to change, and the acceptance scenario
that checks it, with the scenario's exact bytes.

The pin is what keeps a candidate from moving the goalposts. Its bytes are
stored in repo-ai's state directory when it is pinned, and every experiment
runs those bytes, at the base and at the candidate. When the candidate's tree
holds a different version of the scenario, the experiment refuses to run.

Where the bytes came from is part of the record:

* ``worktree``: the file as it was in the working tree when it was pinned;
* ``git``: a blob at a named revision (a reviewer's commit), which anyone can
  check with `git cat-file`;
* ``file``: a file outside the repository.

Pinning from an agent shell is allowed (an agent asked to prove its fix may
write the scenario), and is recorded: a passport then says the oracle may not
be independent. A claim a person pinned from a terminal cannot be replaced
from an agent shell.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

SCHEMA = "repo-ai.proof-claim/1"
MAX_SCENARIO_BYTES = 1024 * 1024
MAX_CLAIM_CHARS = 2000
MAX_SUPPORT = 20
_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
EXIT_REFUSED = 3


class ClaimError(ValueError):
    def __init__(self, message: str, exit_code: int = 1):
        super().__init__(message)
        self.exit_code = exit_code


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def folder(state_dir: Path) -> Path:
    return state_dir / "prove"


def agent_signals(env: dict[str, str] | None = None) -> list[str]:
    """The environment variables that mark an agent shell, a hook or CI
    (the same list capability approval uses)."""
    from ..capabilities import AGENT_ENV
    env = dict(os.environ) if env is None else env
    return [k for k in AGENT_ENV if k in env]


def norm_path(path: str) -> str:
    """A repository-relative POSIX path, or ClaimError."""
    raw = path.replace("\\", "/").strip()
    p = PurePosixPath(raw)
    if not raw or p.is_absolute() or ".." in p.parts or raw.startswith("~"):
        raise ClaimError(f"{path!r}: give a path relative to the repository root, without '..'")
    rel = p.as_posix()
    if rel.split("/")[0].lower() in {".git", ".repo-ai", ".bob"} or any(c in rel for c in "\0\n\r"):
        raise ClaimError(f"{path!r}: repository metadata cannot be a scenario")
    return rel


def _inside(root: Path, rel: str) -> bool:
    """`rel` names a file under `root` through no link (a linked parent
    directory could pin a file from outside the repository)."""
    cur = root
    for part in PurePosixPath(rel).parts[:-1]:
        cur = cur / part
        if cur.is_symlink():
            return False
    return root.resolve() in (root / rel).resolve().parents


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, timeout=60, check=False,
                          stdin=subprocess.DEVNULL)


def read_source(root: Path, rel: str, *, revision: str = "", external: str = "") -> tuple[bytes, dict[str, Any]]:
    """The bytes of a scenario or support file, and where they came from."""
    if revision and external:
        raise ClaimError("--from and --file are exclusive")
    if revision:
        if revision.startswith("-"):
            raise ClaimError(f"{revision!r} is not a revision")
        commit = _git(root, "rev-parse", "--verify", "--quiet", "--end-of-options", f"{revision}^{{commit}}")
        if commit.returncode != 0:
            raise ClaimError(f"{revision!r} does not resolve to a commit")
        commit_id = commit.stdout.decode().strip()
        blob = _git(root, "rev-parse", "--verify", "--quiet", "--end-of-options", f"{commit_id}:{rel}")
        if blob.returncode != 0:
            raise ClaimError(f"{rel} does not exist at {revision}")
        blob_id = blob.stdout.decode().strip()
        kind = _git(root, "cat-file", "-t", blob_id).stdout.decode().strip()
        if kind != "blob":
            raise ClaimError(f"{rel} at {revision} is not a file")
        data = _git(root, "cat-file", "blob", blob_id).stdout
        _check_size(rel, len(data))
        return data, {"kind": "git", "revision": revision, "commit": commit_id, "blob": blob_id}
    if external:
        src = Path(external).expanduser()
        if src.is_symlink() or not src.is_file():
            raise ClaimError(f"{external}: not a regular file")
        return _read_bounded(rel, src), {"kind": "file", "name": src.name}
    src = root / rel
    if src.is_symlink() or not src.is_file() or not _inside(root, rel):
        raise ClaimError(f"{rel}: not a regular file in the working tree (pin a committed version with --from REV, "
                         "or a file outside the repository with --file PATH)")
    return _read_bounded(rel, src), {"kind": "worktree"}


def _read_bounded(rel: str, src: Path) -> bytes:
    with src.open("rb") as fh:  # one read, bounded: the size cannot change between a check and the read
        data = fh.read(MAX_SCENARIO_BYTES + 1)
    _check_size(rel, len(data))
    return data


def _check_size(rel: str, size: int) -> None:
    if size > MAX_SCENARIO_BYTES:
        raise ClaimError(f"{rel}: {size} bytes is more than a scenario may hold ({MAX_SCENARIO_BYTES})")


def _subject_glob(raw: str) -> str:
    """A repository-relative path or glob (`calc/*.py`, `src/**`)."""
    probe = raw.strip().replace("*", "x").replace("?", "x").replace("[", "x").replace("]", "x")
    norm_path(probe)  # the same rules as a path: relative, no '..', no metadata
    return raw.strip().replace("\\", "/")


def _blob_path(state_dir: Path, digest: str) -> Path:
    return folder(state_dir) / "blobs" / digest


def store_blob(state_dir: Path, data: bytes) -> str:
    digest = sha256(data)
    path = _blob_path(state_dir, digest)
    if not path.is_file() or sha256(path.read_bytes()) != digest:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{digest}.{os.getpid()}.tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)
    return digest


def load_blob(state_dir: Path, digest: str) -> bytes:
    """The pinned bytes, checked against their digest (a blob edited in the
    state directory is refused, never run)."""
    try:
        data = _blob_path(state_dir, digest).read_bytes()
    except OSError as exc:
        raise ClaimError(f"the pinned bytes {digest[:12]} are missing from the state directory; pin the claim again")\
            from exc
    if sha256(data) != digest:
        raise ClaimError(f"the pinned bytes {digest[:12]} no longer match their digest; pin the claim again")
    return data


def default_id(text: str, scenario: str) -> str:
    stem = re.sub(r"[^a-z0-9]+", "-", PurePosixPath(scenario).stem.lower()).strip("-")[:40] or "claim"
    return f"{stem}-{sha256((text + chr(0) + scenario).encode())[:6]}"


def settings_digest(record: dict[str, Any]) -> str:
    """Everything that defines the experiment: a passport made under other
    settings is stale."""
    keep = {k: record.get(k) for k in ("claim", "scenario", "support", "targets", "expect_failure", "supersedes",
                                       "runner", "subject")}
    if not keep.get("subject"):
        keep.pop("subject")  # pins made before --subject existed keep their digest
    keep["claim"] = {"sha256": (record.get("claim") or {}).get("sha256")}
    keep["scenario"] = {k: (record.get("scenario") or {}).get(k) for k in ("path", "sha256")}
    keep["support"] = [{k: s.get(k) for k in ("path", "sha256")} for s in record.get("support") or []]
    return sha256(json.dumps(keep, sort_keys=True).encode())


def record_digest(record: dict[str, Any]) -> str:
    """The whole record, who pinned it and its history included: an edit
    outside `prove pin` is detected (not prevented: whoever can write the
    state directory can recompute it)."""
    return sha256(json.dumps({k: v for k, v in record.items() if k != "integrity"}, sort_keys=True).encode())


def pin(root: Path, state_dir: Path, *, text: str, scenario: str, revision: str = "", external: str = "",
        support: list[str] | None = None, targets: list[str] | None = None, expect_failure: str = "",
        supersedes: list[str] | None = None, claim_id: str = "", redact: bool = False, replace: bool = False,
        runner: dict[str, Any] | None = None, env: dict[str, str] | None = None,
        subject: list[str] | None = None) -> dict[str, Any]:
    """Record a claim and its scenario's exact bytes. Reads files; runs nothing."""
    text = " ".join(text.split())
    if not text:
        raise ClaimError("say what the change is supposed to do: `repo-ai prove pin --claim \"...\" --scenario PATH`")
    if len(text) > MAX_CLAIM_CHARS:
        raise ClaimError(f"the claim is longer than {MAX_CLAIM_CHARS} characters")
    rel = norm_path(scenario)
    if expect_failure:
        try:
            re.compile(expect_failure)
        except re.error as exc:
            raise ClaimError(f"--expect-failure is not a valid regular expression: {exc}") from exc
    cid = claim_id or default_id(text, rel)
    if not _ID.match(cid):
        raise ClaimError(f"{cid!r}: a claim id is 1-64 characters of a-z, 0-9, '.', '_' and '-'")
    data, provenance = read_source(root, rel, revision=revision, external=external)
    support_rows: list[dict[str, Any]] = []
    if len(support or []) > MAX_SUPPORT:
        raise ClaimError(f"at most {MAX_SUPPORT} --support files")
    for raw in support or []:
        srel = norm_path(raw)
        if srel == rel or any(s["path"] == srel for s in support_rows):
            continue
        sdata, sprov = read_source(root, srel, revision=revision)
        support_rows.append({"path": srel, "sha256": store_blob(state_dir, sdata), "bytes": len(sdata),
                             "provenance": sprov})
    signals = agent_signals(env)
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    record: dict[str, Any] = {
        "schema": SCHEMA, "id": cid, "created": now,
        "claim": {"text": None if redact else text, "sha256": sha256(text.encode()), "redacted": redact},
        "scenario": {"path": rel, "sha256": store_blob(state_dir, data), "bytes": len(data), "provenance": provenance},
        "support": sorted(support_rows, key=lambda s: s["path"]),
        "targets": sorted(dict.fromkeys(t.strip() for t in targets or [] if t.strip())),
        "expect_failure": expect_failure or None,
        "supersedes": sorted(dict.fromkeys(s.strip() for s in supersedes or [] if s.strip())),
        # the code under test: the only files of the change the scenario runs with (globs, repository-relative)
        "subject": sorted(dict.fromkeys(_subject_glob(s) for s in subject or [] if s.strip())),
        "runner": runner,
        "pinned_by": {"agent_shell": bool(signals), "signals": signals},
        "history": [],
    }
    old = load(state_dir, cid, missing_ok=True)
    if old is not None:
        if settings_digest(old) == settings_digest(record):
            return old  # the same pin: nothing to record
        if not replace:
            raise ClaimError(f"claim {cid!r} is already pinned with other settings; pass --replace to replace it "
                             "(passports of the old pin become stale)")
        if signals and not (old.get("pinned_by") or {}).get("agent_shell"):
            raise ClaimError(f"claim {cid!r} was pinned from a terminal; refusing to replace it from an agent "
                             f"shell, hook or CI ({', '.join(signals)} is set): replace it yourself in a terminal",
                             EXIT_REFUSED)
        record["history"] = [*(old.get("history") or []), {
            "created": old.get("created"), "settings": settings_digest(old),
            "scenario_sha256": (old.get("scenario") or {}).get("sha256"),
            "agent_shell": bool((old.get("pinned_by") or {}).get("agent_shell"))}][-20:]
    record["settings"] = settings_digest(record)
    record["integrity"] = record_digest(record)
    from ..fsutil import atomic_write
    atomic_write(_claim_path(state_dir, cid), json.dumps(record, indent=1, sort_keys=True) + "\n")
    return record


def _claim_path(state_dir: Path, cid: str) -> Path:
    return folder(state_dir) / "claims" / f"{cid}.json"


def load(state_dir: Path, cid: str, missing_ok: bool = False) -> dict[str, Any] | None:
    if not _ID.match(cid):
        raise ClaimError(f"{cid!r} is not a claim id")
    try:
        data = json.loads(_claim_path(state_dir, cid).read_text("utf-8"))
    except FileNotFoundError:
        if missing_ok:
            return None
        raise ClaimError(f"no claim {cid!r} is pinned; `repo-ai prove pin` pins one") from None
    except (OSError, ValueError) as exc:
        raise ClaimError(f"claim {cid!r} cannot be read ({exc}); pin it again") from exc
    if not isinstance(data, dict) or data.get("schema") != SCHEMA or data.get("id") != cid:
        raise ClaimError(f"claim {cid!r} is not a ProofLab claim record; pin it again")
    if data.get("settings") != settings_digest(data) or data.get("integrity") != record_digest(data):
        raise ClaimError(f"claim {cid!r} was edited outside `repo-ai prove pin`; pin it again")
    try:  # a record is data from disk: its paths are checked again, never trusted
        paths = [data["scenario"]["path"], *(s["path"] for s in data.get("support") or [])]
        if any(norm_path(p) != p for p in paths) or len(paths) > MAX_SUPPORT + 1 or not all(
                re.fullmatch(r"[0-9a-f]{64}", h) for h in [data["scenario"]["sha256"],
                                                           *(s["sha256"] for s in data.get("support") or [])]):
            raise ClaimError("bad path or digest")
    except (ClaimError, KeyError, TypeError) as exc:
        raise ClaimError(f"claim {cid!r} holds an invalid path or digest; pin it again") from exc
    return data


def tracked_state(root: Path, state_dir: Path) -> list[str]:
    """Files of ProofLab's state that git tracks: a repository that commits
    claims could hand every clone a pin it never made."""
    try:
        rel = (state_dir / "prove").resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return []
    out = _git(root, "ls-files", "-z", "--", ":(icase,literal)" + rel)  # macOS: `.REPO-AI/` is `.repo-ai/`
    return [p for p in out.stdout.decode("utf-8", "replace").split("\0") if p][:5]


def remove(state_dir: Path, cid: str, env: dict[str, str] | None = None) -> None:
    """Unpin a claim and forget its passports. A claim a person pinned from a
    terminal is not removed from an agent shell."""
    record = load(state_dir, cid)
    assert record is not None
    signals = agent_signals(env)
    if signals and not (record.get("pinned_by") or {}).get("agent_shell"):
        raise ClaimError(f"claim {cid!r} was pinned from a terminal; refusing to remove it from an agent shell, "
                         f"hook or CI ({', '.join(signals)} is set)", EXIT_REFUSED)
    import shutil
    shutil.rmtree(folder(state_dir) / "passports" / cid, ignore_errors=True)
    _claim_path(state_dir, cid).unlink()


def all_ids(state_dir: Path) -> list[str]:
    d = folder(state_dir) / "claims"
    return sorted(p.stem for p in d.glob("*.json") if _ID.match(p.stem)) if d.is_dir() else []


def resolve(state_dir: Path, cid: str | None) -> dict[str, Any]:
    """The named claim, or the only one pinned."""
    if cid:
        found = load(state_dir, cid)
        assert found is not None
        return found
    ids = all_ids(state_dir)
    if not ids:
        raise ClaimError("no claim is pinned yet: `repo-ai prove pin --claim \"what the change does\" --scenario "
                         "tests/test_x.py`")
    if len(ids) > 1:
        raise ClaimError("several claims are pinned; name one (`repo-ai prove status` lists them): "
                         + ", ".join(ids[:20]))
    found = load(state_dir, ids[0])
    assert found is not None
    return found
