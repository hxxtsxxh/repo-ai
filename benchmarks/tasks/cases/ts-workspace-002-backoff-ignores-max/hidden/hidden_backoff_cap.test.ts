import { test } from "node:test";
import assert from "node:assert/strict";
import { backoffDelay, retry } from "../src/retry.ts";

test("delay is capped at maxMs", () => {
  assert.equal(backoffDelay(20), 30_000);
  assert.equal(backoffDelay(10, { baseMs: 1000, maxMs: 5000 }), 5000);
});

test("jitter applies to the capped delay", () => {
  assert.equal(backoffDelay(30, { maxMs: 10_000, jitter: 0.5, random: () => 1 }), 5000);
});

test("retry sleeps never exceed max", async () => {
  const slept: number[] = [];
  await assert.rejects(
    retry(async () => { throw new Error("down"); }, {
      maxAttempts: 6,
      backoff: { baseMs: 1000, maxMs: 3000 },
      sleep: async (ms) => void slept.push(ms),
    }),
  );
  assert.deepEqual(slept, [1000, 2000, 3000, 3000, 3000]);
});

test("regression: exponential growth below cap", () => {
  assert.equal(backoffDelay(3, { baseMs: 100 }), 400);
  assert.throws(() => backoffDelay(0), RangeError);
});
