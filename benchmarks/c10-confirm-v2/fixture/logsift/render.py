"""Turning report rows into text or JSON."""

import json
from collections.abc import Sequence
from typing import Any


def render_table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    """Render rows as aligned columns under a header line.

    Integer columns are right-aligned, all others left-aligned; columns are
    separated by two spaces.
    """
    cells = [list(headers)] + [[str(value) for value in row] for row in rows]
    widths = [max(len(line[i]) for line in cells) for i in range(len(headers))]
    numeric = [bool(rows) and all(isinstance(row[i], int) for row in rows) for i in range(len(headers))]
    lines = []
    for line in cells:
        padded = [
            cell.rjust(width) if is_number else cell.ljust(width)
            for cell, width, is_number in zip(line, widths, numeric)
        ]
        lines.append("  ".join(padded).rstrip())
    return "\n".join(lines) + "\n"


def rows_to_objects(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> list[dict[str, Any]]:
    """Turn rows into a list of objects keyed by the column headers."""
    return [dict(zip(headers, row)) for row in rows]


def render_json(value: Any) -> str:
    """Render a value as indented JSON with sorted keys."""
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
