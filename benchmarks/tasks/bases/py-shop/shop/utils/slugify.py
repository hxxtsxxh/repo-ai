"""URL slugs for product pages."""

import re
import unicodedata

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def slugify(text: str, max_length: int = 60) -> str:
    """``"Crème Brûlée Mug"`` -> ``"creme-brulee-mug"``."""
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    slug = _NON_ALNUM.sub("-", ascii_text.lower()).strip("-")
    if len(slug) > max_length:
        slug = slug[:max_length].rstrip("-")
    return slug


def unique_slug(text: str, existing) -> str:
    """Slugify ``text`` and append ``-2``, ``-3`` ... until it is unused."""
    base = slugify(text) or "item"
    candidate = base
    n = 2
    while candidate in existing:
        candidate = f"{base}-{n}"
        n += 1
    return candidate
