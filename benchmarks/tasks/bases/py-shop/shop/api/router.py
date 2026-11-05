"""A tiny method + path router.

Routes are declared as ``"METHOD /path/{param}"`` strings. Path parameters
match exactly one segment and are passed to the handler as keyword
arguments: ``handler(ctx, request, **params)``.
"""

import re

from shop.api.responses import error_response
from shop.errors import MethodNotAllowed, NotFound, ShopError


def compile_pattern(pattern: str):
    parts = []
    for segment in pattern.strip("/").split("/"):
        if segment.startswith("{") and segment.endswith("}"):
            name = segment[1:-1]
            parts.append(f"(?P<{name}>[^/]+)")
        else:
            parts.append(re.escape(segment))
    return re.compile("^/" + "/".join(parts) + "/?$")


class Route:
    def __init__(self, method: str, pattern: str, handler):
        self.method = method
        self.pattern = pattern
        self.handler = handler
        self.regex = compile_pattern(pattern)

    def match(self, path: str):
        found = self.regex.match(path)
        return found.groupdict() if found else None

    def __repr__(self) -> str:
        return f"Route({self.method} {self.pattern})"


class Router:
    def __init__(self):
        self.routes = []

    def add(self, spec: str, handler) -> Route:
        method, _, pattern = spec.partition(" ")
        route = Route(method.upper(), pattern.strip(), handler)
        self.routes.append(route)
        return route

    def resolve(self, method: str, path: str):
        path = path.split("?", 1)[0]
        allowed = []
        for route in self.routes:
            params = route.match(path)
            if params is None:
                continue
            if route.method == method.upper():
                return route.handler, params
            allowed.append(route.method)
        if allowed:
            raise MethodNotAllowed(f"{method} not allowed on {path}; use {', '.join(allowed)}")
        raise NotFound(f"no route for {method} {path}")

    def dispatch(self, ctx, request: dict) -> dict:
        try:
            handler, params = self.resolve(request["method"], request["path"])
            return handler(ctx, request, **params)
        except ShopError as exc:
            return error_response(exc)
