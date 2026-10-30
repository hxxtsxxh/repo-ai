// createApi() wires the router, authentication, client-version checks and rate limiting.
import { EventBus } from "../../core/src/events.ts";
import { KeyedRateLimiter } from "../../core/src/ratelimit.ts";
import { satisfies } from "../../core/src/semver.ts";
import { TransitionError } from "../../core/src/lifecycle.ts";
import type { KeyTable, Principal, Scope } from "./auth.ts";
import { authenticate, requireScope } from "./auth.ts";
import { HttpError, notFound, tooManyRequests } from "./errors.ts";
import type { ApiRequest, ApiResponse } from "./http.ts";
import { header, json } from "./http.ts";
import type { Handler } from "./router.ts";
import { Router } from "./router.ts";
import { JobStore } from "./store.ts";
import type { JobsContext } from "./jobs.ts";
import { cancelJob, createJob, getJob, listJobs, retryJob } from "./jobs.ts";

export const SUPPORTED_CLIENT_RANGE = "^1.4.0 || ^0.9.2";

export const DEV_KEYS: KeyTable = {
  "dev-admin-key": { name: "dev-admin", scopes: ["admin"] },
  "dev-writer-key": { name: "dev-writer", scopes: ["jobs:read", "jobs:write"] },
  "dev-reader-key": { name: "dev-reader", scopes: ["jobs:read"] },
};

export interface ApiOptions {
  store?: JobStore;
  keys?: KeyTable;
  clock?: () => Date;
  rateLimit?: { capacity: number; refillPerSecond: number } | false;
  supportedClients?: string;
}

export interface Api {
  handle(request: ApiRequest): ApiResponse;
  store: JobStore;
  events: EventBus;
}

function scoped(scope: Scope, handler: Handler): Handler {
  return (request, params, principal) => {
    if (principal) requireScope(principal, scope);
    return handler(request, params, principal);
  };
}

export function toErrorResponse(error: unknown): ApiResponse {
  if (error instanceof HttpError) {
    const headers: Record<string, string> = {};
    if (error.status === 429) {
      const details = error.details as { retryAfterMs: number };
      headers["retry-after"] = String(Math.max(1, Math.ceil(details.retryAfterMs / 1000)));
    }
    const body: Record<string, unknown> = { code: error.code, message: error.message };
    if (error.details !== undefined) body.details = error.details;
    return json(error.status, { error: body }, headers);
  }
  if (error instanceof TransitionError) {
    return json(409, { error: { code: "conflict", message: error.message } });
  }
  const message = error instanceof Error ? error.message : String(error);
  return json(500, { error: { code: "internal", message } });
}

export function createApi(options: ApiOptions = {}): Api {
  const clock = options.clock ?? (() => new Date());
  const store = options.store ?? new JobStore(clock);
  const events = new EventBus();
  const keys = options.keys ?? DEV_KEYS;
  const supportedClients = options.supportedClients ?? SUPPORTED_CLIENT_RANGE;
  const limits = options.rateLimit === undefined ? { capacity: 60, refillPerSecond: 1 } : options.rateLimit;
  const limiter = limits ? new KeyedRateLimiter(limits.capacity, limits.refillPerSecond, () => clock().getTime()) : null;
  const ctx: JobsContext = { store, events, clock };

  const router = new Router()
    .add("GET", "/health", () => json(200, { status: "ok" }))
    .add("GET", "/jobs", scoped("jobs:read", (req) => listJobs(ctx, req)))
    .add("POST", "/jobs", scoped("jobs:write", (req) => createJob(ctx, req)))
    .add("GET", "/jobs/:id", scoped("jobs:read", (_req, p) => getJob(ctx, p.id)))
    .add("POST", "/jobs/:id/cancel", scoped("jobs:write", (_req, p) => cancelJob(ctx, p.id)))
    .add("POST", "/jobs/:id/retry", scoped("jobs:write", (_req, p) => retryJob(ctx, p.id)));

  function checkClientVersion(request: ApiRequest): void {
    const version = header(request, "x-client-version");
    if (version === undefined) return;
    let ok = false;
    try {
      ok = satisfies(version, supportedClients);
    } catch {
      ok = false;
    }
    if (!ok) {
      throw new HttpError(426, "client_outdated", `client ${version} is not supported; need ${supportedClients}`);
    }
  }

  function handle(request: ApiRequest): ApiResponse {
    try {
      const path = request.path.split("?")[0];
      let principal: Principal | null = null;
      if (path !== "/health") {
        checkClientVersion(request);
        principal = authenticate(request, keys);
        if (limiter) {
          const bucket = limiter.bucket(principal.key);
          if (!bucket.tryTake()) throw tooManyRequests(bucket.retryAfterMs());
        }
      }
      const matched = router.match(request.method, path);
      if ("allowed" in matched) {
        if (matched.allowed.length > 0) {
          return json(
            405,
            { error: { code: "method_not_allowed", message: `${request.method} not allowed on ${path}` } },
            { allow: matched.allowed.join(", ") },
          );
        }
        throw notFound(`no route for ${request.method} ${path}`);
      }
      return matched.handler(request, matched.params, principal);
    } catch (error) {
      return toErrorResponse(error);
    }
  }

  return { handle, store, events };
}
