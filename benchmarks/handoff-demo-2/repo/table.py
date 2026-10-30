def render_table(rows):
    """Render rows (lists of strings) as aligned columns separated by ' | '.

    Each column is as wide as its widest cell; cells are left-aligned and padded;
    no trailing whitespace on a line; rows may be ragged (missing cells are empty).
    Returns the lines joined with newlines, or '' for no rows.
    """
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    out = []
    for r in rows:
        out.append(" | ".join(c.ljust(widths[i]) for i, c in enumerate(r)))
    return "\n".join(out)
