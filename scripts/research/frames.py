#!/usr/bin/env python3
"""Extract evidence frames from a video someone gave you (development only).

    python scripts/research/frames.py VIDEO --every 2.5 --out DIR [--max 40]

- Local files only: URLs are refused. This never downloads anything.
- Uses ffprobe/ffmpeg if they are installed. Nothing is installed for you.
- Writes `DIR/frame-<seconds>.jpg` plus `DIR/frames.json` (duration, size,
  timestamps), so ledger observations can cite exact times.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


def probe(video: Path) -> dict:
    exe = shutil.which("ffprobe")
    if not exe:
        raise SystemExit("ffprobe not found (install ffmpeg yourself; this script installs nothing)")
    out = subprocess.run([exe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams",
                          "--", str(video)], capture_output=True, text=True, timeout=60, check=False)
    if out.returncode != 0:
        raise SystemExit(f"ffprobe failed: {out.stderr.strip()[:200]}")
    data = json.loads(out.stdout)
    vstream = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    return {"duration_s": float(data.get("format", {}).get("duration") or 0),
            "width": vstream.get("width"), "height": vstream.get("height"),
            "has_audio": any(s.get("codec_type") == "audio" for s in data.get("streams", []))}


def timestamps(duration: float, every: float, limit: int) -> list[float]:
    if duration <= 0 or every <= 0:
        return []
    out, t = [], min(0.5, duration / 2)
    while t < duration and len(out) < limit:
        out.append(round(t, 2))
        t += every
    return out


def extract(video: Path, out_dir: Path, every: float, limit: int) -> dict:
    if "://" in str(video) or not video.is_file():
        raise SystemExit(f"not a local file: {video}")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise SystemExit("ffmpeg not found (install it yourself; this script installs nothing)")
    meta = probe(video)
    out_dir.mkdir(parents=True, exist_ok=True)
    frames = []
    for t in timestamps(meta["duration_s"], every, limit):
        target = out_dir / f"frame-{t:07.2f}.jpg"
        # `-i` takes the path as its own argument, so a name starting with "-" is not an option
        subprocess.run([ffmpeg, "-v", "error", "-y", "-ss", str(t), "-i", str(video.resolve()),
                        "-frames:v", "1", "-q:v", "3", str(target.resolve())],
                       capture_output=True, timeout=60, check=False)
        if target.is_file():
            frames.append({"at_s": t, "file": target.name})
    meta.update(source=video.name, every_s=every, frames=frames)
    (out_dir / "frames.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return meta


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video", type=Path)
    ap.add_argument("--every", type=float, default=2.5, help="seconds between frames (default 2.5)")
    ap.add_argument("--max", type=int, default=40, help="frame cap (default 40)")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    meta = extract(args.video, args.out, args.every, args.max)
    print(f"{len(meta['frames'])} frame(s) from {meta['duration_s']:.1f}s -> {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
