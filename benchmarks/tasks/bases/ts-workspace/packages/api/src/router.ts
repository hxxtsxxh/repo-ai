// Express-style ":param" routes.
import type { ApiRequest, ApiResponse } from "./http.ts";
import type { Principal } from "./auth.ts";

export type Handler = (
  request: ApiRequest,
  params: Record<string, string>,
  principal: Principal | null,
) => ApiResponse;

interface Route {
  method: string;
  pattern: string;
  regex: RegExp;
  keys: string[];
  handler: Handler;
}

export function compileRoute(pattern: string): { regex: RegExp; keys: string[] } {
  const keys: string[] = [];
  const source = pattern
    .split("/")
    .map((segment) => {
      if (segment.startsWith(":")) {
        keys.push(segment.slice(1));
        return "([^/]+)";
      }
      return segment.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    })
    .join("/");
  return { regex: new RegExp(`^${source}/?$`), keys };
}

export class Router {
  routes: Route[];

  constructor() {
    this.routes = [];
  }

  add(method: string, pattern: string, handler: Handler): this {
    const { regex, keys } = compileRoute(pattern);
    this.routes.push({ method: method.toUpperCase(), pattern, regex, keys, handler });
    return this;
  }

  match(method: string, path: string): { handler: Handler; params: Record<string, string> } | { allowed: string[] } {
    const allowed: string[] = [];
    for (const route of this.routes) {
      const found = route.regex.exec(path);
      if (!found) continue;
      if (route.method !== method.toUpperCase()) {
        allowed.push(route.method);
        continue;
      }
      const params: Record<string, string> = {};
      route.keys.forEach((key, i) => {
        params[key] = decodeURIComponent(found[i + 1]);
      });
      return { handler: route.handler, params };
    }
    return { allowed };
  }
}
