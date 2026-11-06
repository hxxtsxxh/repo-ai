"""Command-line interface: argument parsing and the subcommands."""

import argparse
import sys
from collections.abc import Sequence

from .config import Config, load_config
from .errors import LogsiftError
from .filters import filter_records
from .output import records_to_jsonl, write_text
from .records import LEVELS, read_records
from .render import render_json, render_table, rows_to_objects
from .stats import count_by, top_messages

PROG = "logsift"


def _level(value: str) -> str:
    level = value.upper()
    if level not in LEVELS:
        raise argparse.ArgumentTypeError(f"unknown level {value!r} (choose from {', '.join(LEVELS)})")
    return level


def _positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        number = 0
    if number < 1:
        raise argparse.ArgumentTypeError(f"must be a positive integer: {value!r}")
    return number


def _info(message: str) -> None:
    print(f"{PROG}: {message}", file=sys.stderr)


def _emit_report(args: argparse.Namespace, headers: list[str], rows: list[tuple[str, int]]) -> None:
    if args.format == "json":
        sys.stdout.write(render_json(rows_to_objects(headers, rows)))
    else:
        sys.stdout.write(render_table(headers, rows))


def cmd_summary(args: argparse.Namespace, config: Config) -> int:
    records = filter_records(read_records(args.files), ignore=config.ignore)
    _emit_report(args, [args.by, "count"], count_by(records, args.by))
    return 0


def cmd_filter(args: argparse.Namespace, config: Config) -> int:
    records = filter_records(
        read_records(args.files),
        min_level=args.level,
        components=args.component,
        text=args.grep,
        ignore=config.ignore,
    )
    for record in records:
        sys.stdout.write(record.line + "\n")
    return 0


def cmd_top(args: argparse.Namespace, config: Config) -> int:
    records = filter_records(read_records(args.files), min_level=args.level, ignore=config.ignore)
    _emit_report(args, ["message", "count"], top_messages(records, args.limit))
    return 0


def cmd_export(args: argparse.Namespace, config: Config) -> int:
    records = filter_records(read_records(args.files), min_level=args.level, ignore=config.ignore)
    write_text(args.output, records_to_jsonl(records), force=args.force)
    noun = "record" if len(records) == 1 else "records"
    _info(f"wrote {len(records)} {noun} to {args.output}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=PROG, description="Summarize, filter and export application log files.")
    parser.add_argument("--config", metavar="PATH", help="read settings from this TOML file")
    commands = parser.add_subparsers(dest="command", metavar="COMMAND", required=True)

    summary = commands.add_parser("summary", help="count records by level or component")
    summary.add_argument("files", nargs="+", metavar="FILE", help="log files to read")
    summary.add_argument("--by", choices=["level", "component"], default="level", help="field to count by")
    summary.add_argument("--format", choices=["text", "json"], default="text", help="output format")
    summary.set_defaults(handler=cmd_summary)

    filter_ = commands.add_parser("filter", help="print the lines that match")
    filter_.add_argument("files", nargs="+", metavar="FILE", help="log files to read")
    filter_.add_argument("--level", type=_level, help="lowest level to keep")
    filter_.add_argument(
        "--component", action="append", default=[], metavar="NAME", help="keep this component (repeatable)"
    )
    filter_.add_argument("--grep", metavar="TEXT", help="keep messages containing TEXT")
    filter_.set_defaults(handler=cmd_filter)

    top = commands.add_parser("top", help="list the most frequent messages")
    top.add_argument("files", nargs="+", metavar="FILE", help="log files to read")
    top.add_argument("--level", type=_level, default="WARNING", help="lowest level to count (default: WARNING)")
    top.add_argument("--limit", type=_positive_int, default=10, help="number of messages to list (default: 10)")
    top.add_argument("--format", choices=["text", "json"], default="text", help="output format")
    top.set_defaults(handler=cmd_top)

    export = commands.add_parser("export", help="write records to a JSON Lines file")
    export.add_argument("files", nargs="+", metavar="FILE", help="log files to read")
    export.add_argument("-o", "--output", required=True, metavar="PATH", help="file to write")
    export.add_argument("--level", type=_level, help="lowest level to export")
    export.add_argument("--force", action="store_true", help="replace PATH if it exists")
    export.set_defaults(handler=cmd_export)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        if exc.code is None:
            return 0
        return exc.code if isinstance(exc.code, int) else 2
    try:
        config = load_config(args.config) if args.config else Config()
        return args.handler(args, config)
    except LogsiftError as exc:
        print(f"{PROG}: error: {exc}", file=sys.stderr)
        return 1
