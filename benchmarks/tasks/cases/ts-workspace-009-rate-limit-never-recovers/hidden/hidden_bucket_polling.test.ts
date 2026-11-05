import { test } from "node:test";
import assert from "node:assert/strict";
import { TokenBucket } from "../src/ratelimit.ts";
import { createApi } from "../../api/src/server.ts";

test("frequent polling still accrues tokens", () => {
  let now = 0;
  const bucket = new TokenBucket(1, 1, () => now);
  assert.equal(bucket.tryTake(), true);
  now += 500;
  assert.equal(bucket.tryTake(), false);
  now += 500;
  assert.equal(bucket.tryTake(), true);
});

test("retryAfterMs reflects partial refill", () => {
  let now = 0;
  const bucket = new TokenBucket(1, 1, () => now);
  bucket.tryTake();
  now += 250;
  assert.equal(bucket.retryAfterMs(), 750);
  now += 250;
  assert.equal(bucket.retryAfterMs(), 500);
});

test("api client polling every 500ms recovers", () => {
  let ms = Date.parse("2026-03-02T08:00:00Z");
  const api = createApi({ clock: () => new Date(ms), rateLimit: { capacity: 2, refillPerSecond: 1 } });
  const call = () => api.handle({ method: "GET", path: "/jobs", headers: { authorization: "Bearer dev-admin-key" } });
  assert.equal(call().status, 200);
  assert.equal(call().status, 200);
  const limited = call();
  assert.equal(limited.status, 429);
  assert.equal(limited.headers["retry-after"], "1");
  ms += 500;
  assert.equal(call().status, 429);
  ms += 500;
  assert.equal(call().status, 200);
});

test("regression: burst capacity and cap", () => {
  let now = 0;
  const bucket = new TokenBucket(3, 1, () => now);
  assert.equal(bucket.tryTake(3), true);
  assert.equal(bucket.tryTake(), false);
  now = 60_000;
  assert.equal(bucket.tryTake(3), true);
  assert.equal(bucket.tryTake(), false);
});
