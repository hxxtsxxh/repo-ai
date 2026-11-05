"""Response builders shared by all handlers."""


def json_response(body, status: int = 200, headers=None) -> dict:
    merged = {"Content-Type": "application/json"}
    merged.update(headers or {})
    return {"status": status, "headers": merged, "body": body}


def created(body) -> dict:
    return json_response(body, status=201)


def error_response(exc) -> dict:
    return json_response(
        {"error": {"code": exc.code, "message": str(exc)}}, status=exc.status
    )


def page_response(page, serialize) -> dict:
    return json_response(
        {
            "items": [serialize(item) for item in page.items],
            "page": page.page,
            "per_page": page.per_page,
            "total": page.total,
            "pages": page.pages,
        }
    )
