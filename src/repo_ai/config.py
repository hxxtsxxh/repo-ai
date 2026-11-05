"""Configuration: defaults, file loading, and merge rules.

Config resolution order (later wins):
  1. Built-in defaults below
  2. ~/.config/repo-ai/config.toml            (per-user)
  3. <repo>/.repo-ai/config.toml               (per-repo, written once by init)
  4. <repo>/.repo-ai.toml or repo-ai.toml      (per-repo, hand-written)
  5. Environment variables (REPO_AI_*)
  6. CLI flags

Values are validated: a bad value is recorded in `extra["_bad_config_keys"]`
(reported by `repo-ai doctor`) and the default is kept.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - 3.10 fallback
    import tomli as tomllib  # type: ignore[no-redef]


# Directories that are never worth indexing. Matched as path components.
DEFAULT_EXCLUDE_DIRS: tuple[str, ...] = (
    ".git", ".hg", ".svn", ".bzr",
    "node_modules", "bower_components", "jspm_packages",
    ".venv", "venv", "env", ".env.d", "virtualenv", "__pypackages__",
    "site-packages", ".tox", ".nox", ".mypy_cache", ".pytest_cache",
    ".ruff_cache", "__pycache__", ".ipynb_checkpoints",
    "dist", "build", "out", "output", "bin", "obj", "target",
    ".next", ".nuxt", ".svelte-kit", ".astro", ".docusaurus", ".vitepress",
    ".angular", ".parcel-cache", ".turbo", ".vercel", ".netlify",
    "coverage", "htmlcov", ".coverage", ".nyc_output",
    "vendor", "third_party", "thirdparty", "external", "Pods", "Carthage",
    ".gradle", ".m2", ".cargo", ".stack-work", "_build", "deps",
    ".terraform", ".serverless", ".cache", ".sass-cache", ".eggs",
    ".idea", ".vscode-test", ".DS_Store", ".bob", ".ai", ".repo-ai", ".claude",
    "migrations/versions",  # alembic revision spam
)

# Extensions that are binary, generated, or otherwise useless as context.
DEFAULT_EXCLUDE_EXTS: tuple[str, ...] = (
    # binaries / archives
    ".exe", ".dll", ".so", ".dylib", ".a", ".o", ".obj", ".lib", ".bin",
    ".class", ".jar", ".war", ".ear", ".pyc", ".pyo", ".pyd", ".whl", ".egg",
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar", ".tgz", ".rpm", ".deb",
    ".dmg", ".pkg", ".msi", ".apk", ".aab", ".ipa", ".wasm",
    # media
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".icns", ".tiff", ".webp",
    ".svg", ".mp3", ".mp4", ".avi", ".mov", ".mkv", ".wav", ".flac", ".ogg",
    ".webm", ".psd", ".ai", ".sketch", ".fig",
    # fonts
    ".ttf", ".otf", ".woff", ".woff2", ".eot",
    # data blobs
    ".db", ".sqlite", ".sqlite3", ".mdb", ".parquet", ".avro", ".pb",
    ".pkl", ".pickle", ".npy", ".npz", ".h5", ".hdf5", ".onnx", ".pt", ".pth",
    ".safetensors", ".ckpt", ".model", ".bin.gz",
    # docs that are not plain text
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    # misc
    ".min.js", ".min.css", ".map", ".lock.json",
)

# Files that are lockfiles or generated: recorded as facts, never indexed as text.
DEFAULT_LOCKFILES: tuple[str, ...] = (
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "npm-shrinkwrap.json",
    "poetry.lock", "Pipfile.lock", "uv.lock", "pdm.lock", "conda-lock.yml",
    "Gemfile.lock", "composer.lock", "Cargo.lock", "go.sum", "mix.lock",
    "packages.lock.json", "gradle.lockfile", "flake.lock", "bun.lockb",
)

# Filename globs that almost always contain secrets.
DEFAULT_SECRET_PATH_GLOBS: tuple[str, ...] = (
    ".env", ".env.*", "*.env",
    "*.pem", "*.key", "*.p12", "*.pfx", "*.jks", "*.keystore", "*.ppk",
    "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519",
    "credentials", "credentials.json", "service-account*.json",
    "*secret*.yaml", "*secret*.yml", "*.secrets.*",
    ".npmrc", ".pypirc", ".netrc", ".htpasswd",
    "kubeconfig", "*.kubeconfig",
    "terraform.tfvars", "*.auto.tfvars", "*.tfstate", "*.tfstate.backup",
)


@dataclass(slots=True)
class Config:
    # --- discovery -------------------------------------------------------
    exclude_dirs: tuple[str, ...] = DEFAULT_EXCLUDE_DIRS
    exclude_exts: tuple[str, ...] = DEFAULT_EXCLUDE_EXTS
    lockfiles: tuple[str, ...] = DEFAULT_LOCKFILES
    extra_excludes: tuple[str, ...] = ()
    include_overrides: tuple[str, ...] = ()  # re-include paths excluded by defaults
    respect_gitignore: bool = True
    respect_dockerignore: bool = True
    follow_symlinks: bool = False
    max_file_bytes: int = 1_500_000  # 1.5 MB: bigger files are recorded, not parsed
    max_files: int = 200_000
    min_line_length_for_generated_check: int = 400

    # --- analysis --------------------------------------------------------
    parse_symbols: bool = True
    use_tree_sitter: bool = True  # falls back automatically when unavailable
    git_history_days: int = 365
    git_max_commits: int = 4000
    detect_secrets: bool = True
    workers: int = 0  # 0 = auto (cpu_count)

    # --- output ----------------------------------------------------------
    # Empty means "auto": keep an existing layout, else `.repo-ai/context`
    # (or `.bob/context` for a Bob-only init). See paths.py.
    out_dir: str = ""
    state_dir: str = ""
    write_agents_md: bool = True
    write_skill: bool = True
    write_hooks: bool = True
    write_bobignore: bool = True
    commit_context: bool = True  # if False, gitignore the generated docs
    max_repo_map_entries: int = 400
    max_symbols_per_file_in_docs: int = 12

    # --- agents ------------------------------------------------------------
    # Which agent adapters are wired up. Empty means "whatever init chose";
    # init records its choice in .repo-ai/config.toml / the index.
    agents: tuple[str, ...] = ()
    write_claude_md: bool = True
    write_claude_rules: bool = True
    write_claude_skills: bool = True
    write_claude_agents: bool = True
    write_claude_hooks: bool = True
    management_skills: bool = True  # manual-only /repo-capabilities, /repo-optimize, ...
    # Capability set. "core": verification guidance, context, hooks and curated
    # skills. "full": also subagents, the skeptic reviewer and orchestration
    # hints. "" (an install from before 0.7.6): the earlier defaults. Keys set
    # explicitly anywhere always win over the set.
    feature_set: str = ""
    local_only: bool = False  # hooks in settings.local.json, all outputs gitignored

    # --- retrieval -------------------------------------------------------
    context_budget_tokens: int = 6000  # ceiling for `repo-ai context` output
    max_context_files: int = 14
    hook_budget_tokens: int = 1200  # hard ceiling for prompt-hook injection
    hook_max_files: int = 8
    hook_min_prompt_chars: int = 20
    query_cache: bool = True
    flight_recorder: bool = False  # local, prompt-free diagnostics (`repo-ai debug last`)
    always_loaded_budget_tokens: int = 1500  # cap on repo-ai's always-loaded context (estimate)
    max_generated_skills: int = 8  # Skill Factory: at most this many active generated skills
    skeptic_reviewer: bool = False  # install the advisory repo-skeptic subagent
    orchestration: str = "off"  # off|suggest: mention `repo-ai orchestrate plan` in CLAUDE.md
    verify_gate: bool = False  # Stop hook: block once per change that has no passing `repo-ai verify` evidence
    verify_gate_mode: str = "block"  # block|report: report shows the evidence status to the user, never blocks
    verify_gate_max_blocks: int = 3  # the gate blocks at most this many times per agent session (0: never)
    verify_test_command: str = ""  # the test command `verify` uses when it cannot establish one itself
    skills_llm: str = "off"  # off|on: allow opt-in Tier-2 skill drafting via Claude Code (billable)
    claude_cmd: str = "claude"  # Claude Code executable for opt-in drafting / live eval

    # --- learning / skills --------------------------------------------------
    learning_policy: str = "suggest"  # off|suggest|safe-auto|manual-only-for-risky
    learning_signals: str = "off"  # off|known-commands|outcomes (outcomes ⊃ known-commands)
    skills_mode: str = "curated"  # off|curated|auto
    refresh_debounce_seconds: int = 15

    # --- summarisation ---------------------------------------------------
    summarize: bool = False  # use `bob run` to write narrative prose
    bob_binary: str = "bob"
    summarize_max_cost: str = "0.50"

    # --- misc ------------------------------------------------------------
    verbose: bool = False
    quiet: bool = False
    profile: str = "auto"  # auto|small|large|monorepo

    extra: dict[str, Any] = field(default_factory=dict)


_TUPLE_FIELDS = {
    "exclude_dirs", "exclude_exts", "lockfiles", "extra_excludes",
    "include_overrides", "agents",
}

_CHOICES: dict[str, frozenset[str]] = {
    "learning_policy": frozenset({"off", "suggest", "safe-auto", "manual-only-for-risky"}),
    "learning_signals": frozenset({"off", "known-commands", "outcomes"}),
    "skills_mode": frozenset({"off", "curated", "auto"}),
    "skills_llm": frozenset({"off", "on"}),
    "orchestration": frozenset({"off", "suggest"}),
    "feature_set": frozenset({"", "core", "full"}),
    "profile": frozenset({"auto", "small", "large", "monorepo"}),
}
_VALID_AGENTS = frozenset({"claude", "bob"})

# Keys that existed in earlier releases and are now ignored on purpose.
_RETIRED_KEYS = frozenset({"embeddings", "embedding_model"})


def _coerce(cfg: Config, key: str, value: Any) -> Any:
    current = getattr(cfg, key, None)
    if key in _TUPLE_FIELDS:
        if isinstance(value, str):
            value = [v.strip() for v in value.split(",") if v.strip()]
        value = tuple(str(v) for v in value)
        if key == "agents" and any(v not in _VALID_AGENTS for v in value):
            raise ValueError(f"unknown agent in {value!r}")
        return value
    if key in _CHOICES:
        value = str(value).strip().lower()
        if value not in _CHOICES[key]:
            raise ValueError(f"{key} must be one of {sorted(_CHOICES[key])}")
        return value
    if isinstance(current, bool):
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)
    if isinstance(current, int) and not isinstance(current, bool):
        return int(value)
    if isinstance(current, float):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError(f"{key} must be a finite number")
        return number
    return value


def _apply(cfg: Config, data: dict[str, Any]) -> Config:
    updates: dict[str, Any] = {}
    for key, value in data.items():
        norm = key.replace("-", "_")
        if norm in _RETIRED_KEYS:
            cfg.extra.setdefault("_retired_config_keys", []).append(norm)
            continue
        if not hasattr(cfg, norm) or norm == "extra":
            cfg.extra[norm] = value
            continue
        try:
            updates[norm] = _coerce(cfg, norm, value)
        except (TypeError, ValueError):
            cfg.extra.setdefault("_bad_config_keys", []).append(norm)
    return replace(cfg, **updates) if updates else cfg


_PARSE_ERRORS: list[str] = []


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except FileNotFoundError:
        return {}
    except Exception as exc:  # noqa: BLE001 - reported by doctor, never fatal
        _PARSE_ERRORS.append(f"{path.name}: {exc}")
        return {}
    # Support both a flat table and a [repo-ai] / [tool.repo-ai] section.
    if "repo-ai" in data:
        return data["repo-ai"]
    if "tool" in data and isinstance(data["tool"], dict) and "repo-ai" in data["tool"]:
        return data["tool"]["repo-ai"]
    return data


# Environment variables repo-ai sets for its own child processes.
_INTERNAL_ENV = frozenset({"REPO_AI_IN_HOOK", "REPO_AI_HOOK_DEBUG", "REPO_AI_NO_BACKGROUND",
                           "REPO_AI_EVAL_SUITE", "REPO_AI_HOME"})


def signals_on(cfg: Config) -> bool:
    """Known-command signals are recorded at both opt-in levels."""
    return cfg.learning_signals in {"known-commands", "outcomes"}


def user_config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "repo-ai" / "config.toml"


# Keys a repository's own files may NOT set: they name programs repo-ai runs,
# or switch on sending data to a model. A cloned repository is untrusted, so
# these come only from the user's config, the environment, or CLI flags.
TRUSTED_ONLY_KEYS = frozenset({"claude_cmd", "bob_binary", "summarize", "summarize_max_cost",
                               "skills_llm", "follow_symlinks",
                               # which publishers the Skill Radar fetches from (network)
                               "skill_publishers", "skill_marketplaces"})
# Data-collection keys where the user's own explicit choice beats the
# repository's (e.g. learning_signals = "off" in ~/.config/repo-ai/config.toml
# turns recording off everywhere, whatever a repository commits).
USER_WINS_KEYS = frozenset({"learning_signals", "flight_recorder"})
# Safety switches a repository may tighten but never relax: a cloned repo
# must not get its gitignored local files (and their secrets) indexed.
STRICTER_ONLY_KEYS = {"respect_gitignore": True, "detect_secrets": True}


def _repo_layer(data: dict[str, Any], user_set: set[str], cfg: Config) -> dict[str, Any]:
    out = {}
    for key, value in data.items():
        norm = key.replace("-", "_")
        if norm in TRUSTED_ONLY_KEYS:
            cfg.extra.setdefault("_untrusted_keys_ignored", []).append(norm)
            continue
        if norm in USER_WINS_KEYS and norm in user_set:
            continue
        if norm in STRICTER_ONLY_KEYS and str(value).strip().lower() not in {"1", "true", "yes", "on"}:
            cfg.extra.setdefault("_untrusted_keys_ignored", []).append(norm)
            continue
        out[key] = value
    return out


# What each capability set means. Measured in Option A (v0.7.5): Full's extras
# were never invoked and Full cost about 10% more, so new installs get "core";
# "full" stays one setting away. Data collection (learning_signals) and
# third-party skills are separate, explicit opt-ins in every set.
FEATURE_SETS: dict[str, dict[str, Any]] = {
    "core": {"write_claude_agents": False, "skeptic_reviewer": False, "orchestration": "off"},
    "full": {"write_claude_agents": True, "skeptic_reviewer": True, "orchestration": "suggest",
             "skills_mode": "auto"},
}


def load_config(repo_root: Path, overrides: dict[str, Any] | None = None) -> Config:
    """Build the effective config for a repository."""
    cfg = Config()
    _PARSE_ERRORS.clear()

    user_cfg = user_config_path()
    user_data = _read_toml(user_cfg) if user_cfg.is_file() else {}
    if user_data:
        cfg = _apply(cfg, user_data)
    env_data = {
        key[len("REPO_AI_"):].lower(): value
        for key, value in os.environ.items()
        if key.startswith("REPO_AI_") and key not in _INTERNAL_ENV
    }
    user_set = {k.replace("-", "_") for k in [*user_data, *env_data]}

    explicit = set(user_set)
    managed = repo_root / ".repo-ai" / "config.toml"
    if managed.is_file():
        layer = _repo_layer(_read_toml(managed), user_set, cfg)
        explicit |= {k.replace("-", "_") for k in layer}
        cfg = _apply(cfg, layer)

    for candidate in (".repo-ai.toml", "repo-ai.toml"):
        repo_cfg = repo_root / candidate
        if repo_cfg.is_file():
            layer = _repo_layer(_read_toml(repo_cfg), user_set, cfg)
            explicit |= {k.replace("-", "_") for k in layer}
            cfg = _apply(cfg, layer)
            break

    if env_data:
        cfg = _apply(cfg, env_data)

    if overrides:
        given = {k: v for k, v in overrides.items() if v is not None}
        explicit |= {k.replace("-", "_") for k in given}
        cfg = _apply(cfg, given)
    if not managed.is_file() and "feature_set" not in explicit:
        # no .repo-ai/config.toml yet: a new install, which `init` records as "core"
        cfg = replace(cfg, feature_set="core")
    preset = FEATURE_SETS.get(cfg.feature_set, {})
    chosen = {k: v for k, v in preset.items() if k not in explicit}
    if chosen:
        cfg = replace(cfg, **chosen)
    # keys someone chose: `repo-ai optimize` tuning never overrides these
    cfg.extra["_explicit_keys"] = sorted(explicit)
    if _PARSE_ERRORS:
        cfg.extra["_config_parse_errors"] = list(_PARSE_ERRORS)

    return cfg
