"""Application wiring and demo seed data."""

from dataclasses import dataclass

from shop.api.router import Router
from shop.api.routes import ROUTES
from shop.models.product import Product
from shop.repository.orders import OrderRepository
from shop.repository.payments import PaymentRepository
from shop.repository.products import ProductRepository
from shop.repository.users import UserRepository
from shop.services.discounts import FIXED, PERCENT, Coupon, CouponBook
from shop.services.inventory import InventoryService
from shop.services.notifications import Notifier
from shop.services.orders import OrderService
from shop.services.payments import FakeGateway, PaymentService
from shop.services.users import UserService
from shop.utils.dates import utcnow
from shop.utils.slugify import slugify

ADMIN_EMAIL = "admin@shop.invalid"
ADMIN_PASSWORD = "admin-pass-123"

DEMO_PRODUCTS = [
    ("TEE-0001", "Logo Tee", 1999, ["apparel"]),
    ("MUG-0001", "Crème Brûlée Mug", 1250, ["kitchen"]),
    ("STK-0001", "Sticker Pack", 600, ["accessories"]),
    ("HAT-0001", "Wool Beanie", 2500, ["apparel"]),
    ("BAG-0001", "Canvas Tote", 4500, ["accessories"]),
]

DEMO_COUPONS = [
    Coupon("SAVE10", FIXED, 1000),
    Coupon("PCT15", PERCENT, 15),
    Coupon("BIG20", PERCENT, 20, min_subtotal_cents=10_000),
]


@dataclass
class AppContext:
    products: ProductRepository
    orders: OrderRepository
    users: UserRepository
    payments: PaymentRepository
    inventory: InventoryService
    coupons: CouponBook
    notifier: Notifier
    gateway: FakeGateway
    order_service: OrderService
    payment_service: PaymentService
    user_service: UserService


def build_context(clock=utcnow) -> AppContext:
    products = ProductRepository()
    orders = OrderRepository()
    users = UserRepository()
    payments = PaymentRepository()
    inventory = InventoryService()
    coupons = CouponBook()
    notifier = Notifier(users)
    gateway = FakeGateway()
    order_service = OrderService(orders, products, inventory, coupons, notifier, clock=clock)
    payment_service = PaymentService(payments, order_service, gateway, notifier)
    return AppContext(
        products=products,
        orders=orders,
        users=users,
        payments=payments,
        inventory=inventory,
        coupons=coupons,
        notifier=notifier,
        gateway=gateway,
        order_service=order_service,
        payment_service=payment_service,
        user_service=UserService(users),
    )


def seed(ctx: AppContext, stock: int = 20) -> None:
    for sku, name, price, tags in DEMO_PRODUCTS:
        ctx.products.add(Product(sku, name, price, slug=slugify(name), tags=list(tags)))
        ctx.inventory.set_stock(sku, stock)
    for coupon in DEMO_COUPONS:
        ctx.coupons.add(coupon)
    ctx.user_service.register(ADMIN_EMAIL, "Admin", ADMIN_PASSWORD, roles=("admin",))


class App:
    def __init__(self, ctx: AppContext):
        self.ctx = ctx
        self.router = Router()
        for spec, handler in ROUTES:
            self.router.add(spec, handler)

    def request(self, method, path, body=None, headers=None, query=None) -> dict:
        req = {
            "method": method.upper(),
            "path": path,
            "headers": dict(headers or {}),
            "query": dict(query or {}),
            "body": body if body is not None else {},
        }
        return self.router.dispatch(self.ctx, req)

    # Convenience for scripts and tests -------------------------------------
    def login(self, email: str, password: str) -> dict:
        resp = self.request("POST", "/auth/login", body={"email": email, "password": password})
        if resp["status"] != 200:
            raise RuntimeError(f"login failed: {resp['body']}")
        return {"Authorization": f"Bearer {resp['body']['token']}"}

    def register_and_login(self, email: str, password: str = "customer-pass-1") -> dict:
        resp = self.request("POST", "/users", body={"email": email, "password": password})
        if resp["status"] != 201:
            raise RuntimeError(f"registration failed: {resp['body']}")
        return self.login(email, password)


def create_app(seed_data: bool = True, clock=utcnow) -> App:
    ctx = build_context(clock=clock)
    if seed_data:
        seed(ctx)
    return App(ctx)
