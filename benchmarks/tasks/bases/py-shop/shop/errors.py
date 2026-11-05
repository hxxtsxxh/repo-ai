"""Exception hierarchy. Every error carries an HTTP status and a short code."""


class ShopError(Exception):
    status = 400
    code = "bad_request"


class ValidationError(ShopError):
    status = 422
    code = "validation_error"


class AuthError(ShopError):
    status = 401
    code = "unauthorized"


class Forbidden(ShopError):
    status = 403
    code = "forbidden"


class NotFound(ShopError):
    status = 404
    code = "not_found"


class MethodNotAllowed(ShopError):
    status = 405
    code = "method_not_allowed"


class Conflict(ShopError):
    status = 409
    code = "conflict"


class OutOfStock(Conflict):
    code = "out_of_stock"


class PaymentError(ShopError):
    status = 402
    code = "payment_failed"
