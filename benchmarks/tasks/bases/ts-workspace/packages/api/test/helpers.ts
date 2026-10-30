import { createApi } from "../src/server.ts";
import type { ApiOptions } from "../src/server.ts";

export const ADMIN = { authorization: "Bearer dev-admin-key" };
export const READER = { authorization: "Bearer dev-reader-key" };

export function fixedClock(iso = "2026-03-02T08:00:00Z") {
  let current = new Date(iso).getTime();
  const clock = () => new Date(current);
  return Object.assign(clock, { advance: (ms: number) => void (current += ms) });
}

export function setup(options: ApiOptions = {}) {
  const clock = fixedClock();
  const api = createApi({ clock, rateLimit: false, ...options });
  return { api, clock };
}
