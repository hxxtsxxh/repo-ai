import { test } from "node:test";
import assert from "node:assert/strict";
import { resolveConfig } from "../src/config.ts";

test("environment beats config file", () => {
  const config = resolveConfig({ file: { concurrency: 2, defaultTimeoutMs: 1000 }, env: { RUNNER_CONCURRENCY: "8", RUNNER_TIMEOUT: "2m" } });
  assert.equal(config.concurrency, 8);
  assert.equal(config.defaultTimeoutMs, 120_000);
});

test("overrides beat environment and file", () => {
  const config = resolveConfig({
    file: { logLevel: "warn", maxAttempts: 2 },
    env: { RUNNER_LOG_LEVEL: "DEBUG", RUNNER_MAX_ATTEMPTS: "4" },
    overrides: { maxAttempts: 9, logLevel: undefined },
  });
  assert.equal(config.maxAttempts, 9);
  assert.equal(config.logLevel, "debug");
});

test("regression: file beats defaults, unset env ignored", () => {
  const config = resolveConfig({ file: { apiPort: 9000 }, env: { RUNNER_CONCURRENCY: "" } });
  assert.equal(config.apiPort, 9000);
  assert.equal(config.concurrency, 4);
});
