"""Where repo-ai keeps things.

Two layouts exist, and every module asks this one for paths instead of
hard-coding them:

  standard (new installs, `--agent claude|both`)
      .repo-ai/config.toml     human-editable settings, created once
      .repo-ai/context/        generated docs + facts.json (regenerable)
      .repo-ai/state/          index.db, caches, locks, dirty markers (gitignored)
      .repo-ai/learning/       learned-rule ledger and skill provenance

  legacy (v0.4 Bob installs, `repo-ai init` with no `--agent`)
      .bob/context/            docs, facts.json, index.db — exactly as v0.4
      .bob/context/learning/   learning ledger (only if learning is enabled)

An explicit `out_dir` (config, `REPO_AI_OUT_DIR`) always wins and keeps the
v0.4 behaviour of storing the index next to the docs unless `state_dir` is
also set. Existing indexes are detected before defaults are applied, so an
upgrade never silently moves anyone's data.
"""

from __future__ import annotations

import os

from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .config import Config

HOME_DIR = ".repo-ai"
LEGACY_CONTEXT = ".bob/context"


class LayoutError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Layout:
    root: Path
    kind: str  # standard | legacy | custom
    context_dir: Path
    state_dir: Path
    learning_dir: Path

    # -- derived paths ------------------------------------------------------
    @property
    def index_path(self) -> Path:
        return self.state_dir / "index.db"

    @property
    def dirty_path(self) -> Path:
        return self.state_dir / ".dirty"

    @property
    def lock_path(self) -> Path:
        return self.state_dir / "update.lock"

    @property
    def stamp_path(self) -> Path:
        return self.state_dir / "last-refresh"

    @property
    def signals_path(self) -> Path:
        return self.state_dir / "signals.jsonl"

    @property
    def originals_path(self) -> Path:
        return self.state_dir / "originals.json"

    @property
    def backup_dir(self) -> Path:
        return self.state_dir / "backups"

    @property
    def config_path(self) -> Path:
        return self.root / HOME_DIR / "config.toml"

    def rel(self, path: Path) -> str:
        """POSIX path relative to the repository root."""
        return PurePosixPath(path.relative_to(self.root).as_posix()).as_posix()

    @property
    def context_rel(self) -> str:
        return self.rel(self.context_dir)

    @property
    def state_rel(self) -> str:
        return self.rel(self.state_dir)

    @property
    def learning_rel(self) -> str:
        return self.rel(self.learning_dir)

    def runtime_ignore_entries(self) -> list[str]:
        """Paths that must never be committed (machine-local state)."""
        if self.state_dir == self.context_dir:
            base = self.state_rel
            return [f"{base}/index.db", f"{base}/index.db-wal", f"{base}/index.db-shm",
                    f"{base}/.dirty", f"{base}/update.lock", f"{base}/last-refresh",
                    f"{base}/signals.jsonl", f"{base}/originals.json", f"{base}/flight.jsonl",
                    f"{base}/ranking.json", f"{base}/episodes/", f"{base}/backups/",
                    # `repo-ai verify`: runtime records, evidence, caches, the gate's state
                    f"{base}/missions/", f"{base}/testmap.json", f"{base}/gate.json", f"{base}/verify-*.json", f"{base}/evidence/"]
        return [f"{self.state_rel}/"]

    def owned_dirs(self) -> list[Path]:
        """Directories whose entire contents repo-ai owns."""
        dirs = [self.context_dir, self.state_dir, self.learning_dir]
        out: list[Path] = []
        for d in dirs:
            if d not in out:
                out.append(d)
        return out


def _inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _checked(root: Path, rel: str, key: str) -> Path:
    if not rel or rel.strip() in {".", "./"}:
        raise LayoutError(f"{key} must name a subdirectory of the repository")
    path = (root / rel).resolve() if not Path(rel).is_absolute() else Path(rel).resolve()
    if not _inside(root, path) or path == root.resolve():
        raise LayoutError(f"{key}={rel!r} resolves outside the repository; refusing")
    return root / path.relative_to(root.resolve())


def detect_kind(root: Path) -> str:
    """Which layout already exists on disk, or '' for none."""
    if (root / HOME_DIR / "state" / "index.db").is_file():
        return "standard"
    if (root / LEGACY_CONTEXT / "index.db").is_file():
        return "legacy"
    if (root / HOME_DIR / "config.toml").is_file():
        return "standard"
    return ""


def _no_symlinks(root: Path, *dirs: Path) -> None:
    """repo-ai's own directories, and every entry inside them, must be real
    files: a repository could commit `.repo-ai/state/update.lock -> ~/.zshrc`
    and have the lock, dirty marker or index write outside the repository."""
    for directory in dirs:
        try:
            rel = directory.relative_to(root)
        except ValueError:
            continue
        current = root
        for part in rel.parts:
            current = current / part
            if current.is_symlink():
                raise LayoutError(f"{current.relative_to(root).as_posix()} is a symlink; repo-ai "
                                  "keeps its state inside the repository and will not follow it")
        if not directory.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(directory):
            for name in [*dirnames, *filenames]:
                entry = Path(dirpath) / name
                if entry.is_symlink():
                    raise LayoutError(
                        f"{entry.relative_to(root).as_posix()} is a symlink inside repo-ai's "
                        "state; refusing to use it (delete it, then re-run)")


def make_dir(root: Path, path: Path, mode: int = 0o777) -> Path:
    """Create one of repo-ai's own directories. A FILE where one of its components goes (a repository that tracks
    a file named `.repo-ai`) is refused by name, not with ENOTDIR; reading a layout never needs the directory."""
    try:
        path.mkdir(parents=True, exist_ok=True, mode=mode)
    except (FileExistsError, NotADirectoryError) as exc:
        try:
            parts = path.relative_to(root).parts
        except ValueError:  # outside the repository (a configured state_dir elsewhere): an ordinary OS error
            raise exc from None
        current = root
        for part in parts:
            current = current / part
            if os.path.lexists(current) and not current.is_dir():
                raise LayoutError(f"{current.relative_to(root).as_posix()} is a file in this repository; repo-ai "
                                  "keeps its state in a directory of that name (set out_dir in repo-ai.toml)") from exc
        raise
    return path


def resolve_layout(root: Path, cfg: Config, prefer: str = "standard") -> Layout:
    layout = _resolve_layout(root, cfg, prefer)
    _no_symlinks(root, layout.context_dir, layout.state_dir, layout.learning_dir)
    return layout


def _resolve_layout(root: Path, cfg: Config, prefer: str = "standard") -> Layout:
    """Resolve the layout for `root`.

    Precedence: explicit `out_dir` > layout already on disk > `prefer`.
    `prefer` is 'legacy' for a Bob-only `repo-ai init` (keeps v0.4 output
    byte-compatible) and 'standard' otherwise.
    """
    if cfg.out_dir:
        context_dir = _checked(root, cfg.out_dir, "out_dir")
        state_dir = _checked(root, cfg.state_dir, "state_dir") if cfg.state_dir else context_dir
        return Layout(root, "custom", context_dir, state_dir, context_dir / "learning")

    kind = detect_kind(root) or prefer
    if kind == "legacy":
        context_dir = root / LEGACY_CONTEXT
        state_dir = _checked(root, cfg.state_dir, "state_dir") if cfg.state_dir else context_dir
        return Layout(root, "legacy", context_dir, state_dir, context_dir / "learning")

    home = root / HOME_DIR
    state_dir = _checked(root, cfg.state_dir, "state_dir") if cfg.state_dir else home / "state"
    return Layout(root, "standard", home / "context", state_dir, home / "learning")
