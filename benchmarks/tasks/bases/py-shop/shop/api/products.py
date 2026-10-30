"""Catalog endpoints."""

from shop.api.middleware import query_int, require_admin
from shop.api.responses import created, json_response, page_response
from shop.api.serializers import serialize_product
from shop.errors import NotFound, ValidationError
from shop.models.product import Product
from shop.utils.money import to_cents
from shop.utils.pagination import paginate
from shop.utils.slugify import unique_slug
from shop.utils.validation import require_fields, validate_sku


def list_products(ctx, request):
    tag = (request.get("query") or {}).get("tag")
    products = ctx.products.active(tag=tag)
    page = paginate(
        products,
        page=query_int(request, "page", 1),
        per_page=query_int(request, "per_page"),
    )
    return page_response(page, serialize_product)


def get_product(ctx, request, slug):
    product = ctx.products.by_slug(slug)
    if product is None or not product.active:
        raise NotFound(f"product {slug} not found")
    body = serialize_product(product)
    body["available"] = ctx.inventory.available(product.sku)
    return json_response(body)


def create_product(ctx, request):
    require_admin(ctx, request)
    body = request.get("body") or {}
    require_fields(body, "sku", "name", "price")
    try:
        price_cents = to_cents(body["price"])
    except (TypeError, ValueError) as exc:
        raise ValidationError(str(exc)) from exc
    if price_cents <= 0:
        raise ValidationError("price must be positive")
    product = Product(
        sku=validate_sku(body["sku"]),
        name=body["name"].strip(),
        price_cents=price_cents,
        slug=unique_slug(body["name"], ctx.products.slugs()),
        tags=list(body.get("tags", [])),
    )
    ctx.products.add(product)
    ctx.inventory.set_stock(product.sku, int(body.get("stock", 0)))
    return created(serialize_product(product))
