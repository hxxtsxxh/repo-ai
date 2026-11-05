import { test } from "node:test";
import assert from "node:assert/strict";
import { EventBus } from "../src/events.ts";
import { TokenBucket } from "../src/ratelimit.ts";
import { resolveConfig } from "../src/config.ts";
import { canTransition } from "../src/lifecycle.ts";
import { pluralize } from "../src/strings.ts";

test("event bus delivers and unsubscribes", () => {
  const bus = new EventBus();
  const seen: number[] = [];
  const off = bus.on<number>("tick", (n) => seen.push(n));
  bus.emit("tick", 1);
  off();
  bus.emit("tick", 2);
  assert.deepEqual(seen, [1]);
});

test("once fires a single time", () => {
  const bus = new EventBus();
  let count = 0;
  bus.once("x", () => count++);
  bus.emit("x", null);
  bus.emit("x", null);
  assert.equal(count, 1);
});

test("token bucket allows bursts up to capacity", () => {
  let now = 0;
  const bucket = new TokenBucket(2, 1, () => now);
  assert.equal(bucket.tryTake(), true);
  assert.equal(bucket.tryTake(), true);
  assert.equal(bucket.tryTake(), false);
  now = 5_000;
  assert.equal(bucket.tryTake(), true);
});

test("config defaults", () => {
  const config = resolveConfig();
  assert.equal(config.concurrency, 4);
  assert.equal(config.logLevel, "info");
});

test("config file values override defaults", () => {
  assert.equal(resolveConfig({ file: { maxAttempts: 7 } }).maxAttempts, 7);
});

test("lifecycle", () => {
  assert.equal(canTransition("queued", "running"), true);
  assert.equal(canTransition("succeeded", "queued"), false);
});

test("pluralize", () => {
  assert.equal(pluralize(1, "job"), "1 job");
  assert.equal(pluralize(3, "job"), "3 jobs");
});
