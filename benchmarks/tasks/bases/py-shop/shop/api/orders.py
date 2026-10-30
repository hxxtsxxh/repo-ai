"""Order endpoints."""

from shop.api.middleware import current_user, is_admin, query_int, require_admin
from shop.api.responses import created, json_response, page_response
from shop.api.serializers import serialize_order, serialize_payment
from shop.errors import NotFound
from shop.utils.pagination import paginate
from shop.utils.validation import require_fields


def _visible_order(ctx, user: dict, order_id: str):
    order = ctx.order_service.get(order_id)
    if order.user_id != user["sub"] and not is_admin(user):
        # Do not reveal that another customer's order exists.
        raise NotFound(f"order {order_id} not found")
    return order


def list_orders(ctx, request):
    user = current_user(ctx, request)
    orders = ctx.order_service.list_for_user(user["sub"])
    page = paginate(
        orders,
        page=query_int(request, "page", 1),
        per_page=query_int(request, "per_page"),
    )
    return page_response(page, serialize_order)


def get_order(ctx, request, order_id):
    user = current_user(ctx, request)
    return json_response(serialize_order(_visible_order(ctx, user, order_id)))


def create_order(ctx, request):
    user = current_user(ctx, request)
    body = request.get("body") or {}
    require_fields(body, "items")
    order = ctx.order_service.place_order(
        user["sub"],
        body["items"],
        region=body.get("region", "CA"),
        coupon_codes=body.get("coupons", []),
        shipping_method=body.get("shipping_method", "standard"),
    )
    return created(serialize_order(order))


def cancel_order(ctx, request, order_id):
    user = current_user(ctx, request)
    _visible_order(ctx, user, order_id)
    order = ctx.order_service.cancel(order_id)
    return json_response(serialize_order(order))


def ship_order(ctx, request, order_id):
    require_admin(ctx, request)
    order = ctx.order_service.ship(order_id)
    return json_response(serialize_order(order))


def list_order_payments(ctx, request, order_id):
    user = current_user(ctx, request)
    _visible_order(ctx, user, order_id)
    payments = ctx.payments.for_order(order_id)
    return json_response({"items": [serialize_payment(p) for p in payments]})
