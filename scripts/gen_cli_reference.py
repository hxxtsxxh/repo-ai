"""Generate the CLI reference from repo-ai's own argparse parser.

The reference is rendered from the parser's structure (commands, arguments,
choices, help strings), not from `--help` text, so it is identical on every
Python version (argparse's help layout changed between 3.10 and 3.13).

    python scripts/gen_cli_reference.py           # write the reference files
    python scripts/gen_cli_reference.py --check   # exit 1 if any is out of date

Targets: docs/CLI-REFERENCE.md, and the docs site page when site/ exists.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from repo_ai.cli import build_parser  # noqa: E402

DOCS_TARGET = ROOT / "docs" / "CLI-REFERENCE.md"
SITE_TARGET = ROOT / "site" / "src" / "content" / "docs" / "reference" / "cli.md"

HEADER = (
    "Generated from the installed parser by `scripts/gen_cli_reference.py`; do not edit by hand.\n"
    "`repo-ai <command> --help` prints the same arguments. Commands marked *(experimental)* are\n"
    "described in the status matrix.\n"
)


def _subcommands(parser: argparse.ArgumentParser) -> list[tuple[str, list[str], str, argparse.ArgumentParser]]:
    """Visible subcommands as (name, aliases, help, parser), in registration order."""
    out = []
    for action in parser._actions:
        if not isinstance(action, argparse._SubParsersAction):
            continue
        by_parser: dict[int, list[str]] = {}
        for name, sub in action.choices.items():
            by_parser.setdefault(id(sub), []).append(name)
        for choice in action._choices_actions:  # only commands registered with help=
            sub = action.choices[choice.dest]
            names = by_parser[id(sub)]
            out.append((choice.dest, [n for n in names if n != choice.dest], choice.help or "", sub))
    return out


def _expand(parser: argparse.ArgumentParser, action: argparse.Action) -> str:
    text = action.help or ""
    if "%" in text:
        text = parser._get_formatter()._expand_help(action)
    return " ".join(text.split())


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("<", "&lt;").replace(">", "&gt;")


def _arg_label(action: argparse.Action) -> str:
    if action.option_strings:
        label = ", ".join(f"`{o}`" for o in action.option_strings)
        if action.nargs != 0:
            metavar = action.metavar or action.dest.upper()
            if isinstance(metavar, tuple):
                metavar = " ".join(metavar)
            label += f" `{metavar}`"
        return label
    metavar = action.metavar or action.dest
    if isinstance(metavar, tuple):
        metavar = " ".join(metavar)
    return f"`{metavar}`"


def _arguments(parser: argparse.ArgumentParser) -> list[str]:
    rows = []
    for action in parser._actions:
        if isinstance(action, (argparse._HelpAction, argparse._SubParsersAction)):
            continue
        if action.help == argparse.SUPPRESS:
            continue
        desc = _expand(parser, action)
        if action.choices is not None and not isinstance(action.choices, dict):
            choices = ", ".join(f"`{c}`" for c in action.choices)
            desc = f"{desc} (one of {choices})" if desc else f"one of {choices}"
        if action.required and action.option_strings:
            desc = f"**required.** {desc}"
        rows.append(f"| {_arg_label(action)} | {_cell(desc)} |")
    if not rows:
        return []
    return ["| Argument | Description |", "|---|---|", *rows]


def _section(path: list[str], help_text: str, aliases: list[str], parser: argparse.ArgumentParser,
             level: int) -> list[str]:
    title = " ".join(path)
    lines = [f"{'#' * level} `{title}`", ""]
    if aliases:
        lines += [f"Alias: {', '.join(f'`{a}`' for a in aliases)}.", ""]
    summary = " ".join((help_text or parser.description or "").split())
    if summary:
        lines += [_cell(summary), ""]
    args = _arguments(parser)
    if args:
        lines += [*args, ""]
    for name, sub_aliases, sub_help, sub in _subcommands(parser):
        lines += _section([*path, name], sub_help, sub_aliases, sub, min(level + 1, 6))
    return lines


def render() -> str:
    parser = build_parser()
    lines = ["# CLI reference", "", HEADER, "## Commands", ""]
    commands = _subcommands(parser)
    lines += ["| Command | Summary |", "|---|---|"]
    lines += [f"| [`{n}`](#{_anchor(n)}) | {_cell(' '.join(h.split()))} |" for n, _a, h, _p in commands]
    lines += ["", "## Global options", "", *_arguments(parser), ""]
    for name, aliases, help_text, sub in commands:
        lines += _section(["repo-ai", name], help_text, aliases, sub, 2)
    return "\n".join(lines).rstrip() + "\n"


def _anchor(name: str) -> str:
    return f"repo-ai-{name}".lower().replace("_", "-")


def _site_page(body: str) -> str:
    _title, _blank, rest = body.split("\n", 2)
    front = "---\ntitle: CLI reference\ndescription: Every repo-ai command and argument, generated from the parser.\n---\n"
    return front + rest


def targets() -> dict[Path, str]:
    body = render()
    out = {DOCS_TARGET: body}
    if SITE_TARGET.parent.parent.is_dir():  # site/src/content/docs exists
        out[SITE_TARGET] = _site_page(body)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="exit 1 if a target is out of date")
    args = ap.parse_args(argv)
    stale = []
    for path, text in targets().items():
        current = path.read_text(encoding="utf-8") if path.exists() else None
        if current == text:
            continue
        if args.check:
            stale.append(path.relative_to(ROOT).as_posix())
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")
            print(f"wrote {path.relative_to(ROOT).as_posix()}")
    if stale:
        print("out of date (run python scripts/gen_cli_reference.py): " + ", ".join(stale), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
