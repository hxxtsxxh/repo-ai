import { test } from "node:test";
import assert from "node:assert/strict";
import { backoffDelay, retry } from "../src/retry.ts";

test("backoff grows exponentially", () => {
  assert.equal(backoffDelay(1, { baseMs: 100 }), 100);
  assert.equal(backoffDelay(2, { baseMs: 100 }), 200);
  assert.equal(backoffDelay(4, { baseMs: 100 }), 800);
});

test("jitter shaves time off", () => {
  assert.equal(backoffDelay(1, { baseMs: 1000, jitter: 0.5, random: () => 1 }), 500);
});

test("retry eventually succeeds", async () => {
  let calls = 0;
  const slept: number[] = [];
  const result = await retry(
    async () => {
      calls += 1;
      if (calls < 3) throw new Error("flaky");
      return "ok";
    },
    { maxAttempts: 5, backoff: { baseMs: 10 }, sleep: async (ms) => void slept.push(ms) },
  );
  assert.equal(result, "ok");
  assert.deepEqual(slept, [10, 20]);
});

test("retry gives up after maxAttempts", async () => {
  await assert.rejects(
    retry(async () => { throw new Error("nope"); }, { maxAttempts: 2, sleep: async () => {} }),
    /nope/,
  );
});
