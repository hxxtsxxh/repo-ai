#!/usr/bin/env python3
"""Compact, verifiable storage for verify-eval raw evidence.

Raw per-project outputs (changes with the changed files' full contents,
ground truth, selections) are large and highly redundant. They are kept as
one deterministic ``.tar.xz`` per evidence set, with a manifest that records
the SHA-256 of every original file and of the archive itself, and the commit
where the uncompressed originals were last committed.

    python archive.py pack    <dir> <out.tar.xz> --commit <sha> [--note TEXT]
    python archive.py verify  <archive.tar.xz>      # archive and every file against the manifest
    python archive.py unpack  <archive.tar.xz> <dest>

``pack`` refuses to overwrite an existing archive, and never deletes its
input. Unpacking checks every file's hash before writing anything.
Standard library only.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import lzma
import sys
import tarfile
from pathlib import Path, PurePosixPath


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def manifest_path(archive: Path) -> Path:
    return archive.with_name(archive.name.removesuffix(".tar.xz") + ".manifest.json")


def pack(src: Path, out: Path, commit: str, note: str = "") -> dict:
    if out.exists() or manifest_path(out).exists():
        raise SystemExit(f"refusing to overwrite {out} (archives are immutable)")
    files = sorted(p for p in src.rglob("*") if p.is_file() and not p.is_symlink())
    entries: dict[str, str] = {}
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.USTAR_FORMAT) as tar:
        for p in files:
            rel = p.relative_to(src).as_posix()
            data = p.read_bytes()
            entries[rel] = _sha(data)
            info = tarfile.TarInfo(rel)
            info.size, info.mtime, info.mode = len(data), 0, 0o644
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            tar.addfile(info, io.BytesIO(data))
    blob = lzma.compress(buf.getvalue(), preset=9 | lzma.PRESET_EXTREME)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(blob)
    meta = {"archive": out.name, "archive_sha256": _sha(blob), "archive_bytes": len(blob),
            "uncompressed_bytes": sum((src / r).stat().st_size for r in entries),
            "file_count": len(entries), "source_commit": commit, "note": note, "files": entries}
    manifest_path(out).write_text(json.dumps(meta, indent=1, sort_keys=True) + "\n", "utf-8")
    # round trip before reporting success: the archive must reproduce every input byte
    verify(out)
    return meta


def _members(archive: Path) -> tuple[dict, dict[str, bytes]]:
    meta = json.loads(manifest_path(archive).read_text("utf-8"))
    blob = archive.read_bytes()
    if _sha(blob) != meta["archive_sha256"]:
        raise SystemExit(f"{archive.name}: archive hash does not match its manifest")
    out: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(lzma.decompress(blob)), mode="r") as tar:
        for m in tar.getmembers():
            rel = PurePosixPath(m.name)
            if not m.isfile() or rel.is_absolute() or ".." in rel.parts:
                raise SystemExit(f"{archive.name}: unexpected member {m.name!r}")
            f = tar.extractfile(m)
            out[m.name] = f.read() if f else b""
    if set(out) != set(meta["files"]):
        raise SystemExit(f"{archive.name}: file list differs from the manifest")
    bad = [n for n, data in out.items() if _sha(data) != meta["files"][n]]
    if bad:
        raise SystemExit(f"{archive.name}: {len(bad)} file(s) fail their hash, e.g. {bad[0]}")
    return meta, out


def verify(archive: Path) -> dict:
    meta, _ = _members(archive)
    return meta


def unpack(archive: Path, dest: Path) -> int:
    _, members = _members(archive)
    for name, data in members.items():
        target = dest / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return len(members)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pack")
    p.add_argument("src", type=Path)
    p.add_argument("out", type=Path)
    p.add_argument("--commit", required=True)
    p.add_argument("--note", default="")
    p = sub.add_parser("verify")
    p.add_argument("archive", type=Path, nargs="+")
    p = sub.add_parser("unpack")
    p.add_argument("archive", type=Path)
    p.add_argument("dest", type=Path)
    a = ap.parse_args(argv)
    if a.cmd == "pack":
        meta = pack(a.src, a.out, a.commit, a.note)
        print(f"{a.out.name}: {meta['file_count']} files, {meta['uncompressed_bytes']} -> "
              f"{meta['archive_bytes']} bytes, sha256 {meta['archive_sha256'][:16]}… (verified)")
    elif a.cmd == "verify":
        for arc in a.archive:
            meta = verify(arc)
            print(f"{arc.name}: OK ({meta['file_count']} files, source commit {meta['source_commit'][:12]})")
    else:
        print(f"unpacked {unpack(a.archive, a.dest)} files into {a.dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
