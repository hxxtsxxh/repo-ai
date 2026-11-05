"""Offset pagination shared by every list endpoint."""

from dataclasses import dataclass, field

from shop import config


@dataclass
class Page:
    items: list = field(default_factory=list)
    page: int = 1
    per_page: int = config.DEFAULT_PAGE_SIZE
    total: int = 0
    pages: int = 0

    @property
    def has_next(self) -> bool:
        return self.page < self.pages


def clamp_per_page(per_page) -> int:
    if per_page is None:
        return config.DEFAULT_PAGE_SIZE
    per_page = int(per_page)
    if per_page < 1:
        return 1
    return min(per_page, config.MAX_PAGE_SIZE)


def paginate(items, page=1, per_page=None) -> Page:
    """Return one page of ``items`` (1-based ``page``)."""
    items = list(items)
    per_page = clamp_per_page(per_page)
    page = max(1, int(page or 1))
    total = len(items)
    pages = (total + per_page - 1) // per_page if total else 0
    if pages and page > pages:
        return Page(items=[], page=page, per_page=per_page, total=total, pages=pages)
    start = (page - 1) * per_page
    return Page(
        items=items[start : start + per_page],
        page=page,
        per_page=per_page,
        total=total,
        pages=pages,
    )
