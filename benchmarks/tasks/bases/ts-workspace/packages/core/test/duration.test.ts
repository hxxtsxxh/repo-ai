import { test } from "node:test";
import assert from "node:assert/strict";
import { formatDuration, parseDuration } from "../src/duration.ts";

test("parses single units", () => {
  assert.equal(parseDuration("90s"), 90_000);
  assert.equal(parseDuration("5m"), 300_000);
  assert.equal(parseDuration("2h"), 7_200_000);
});

test("parses combined units and whitespace", () => {
  assert.equal(parseDuration("1h30m"), 5_400_000);
  assert.equal(parseDuration("1h 30m"), 5_400_000);
});

test("bare numbers are seconds", () => {
  assert.equal(parseDuration("15"), 15_000);
  assert.equal(parseDuration(1234), 1234);
});

test("rejects garbage", () => {
  assert.throws(() => parseDuration("soon"), SyntaxError);
  assert.throws(() => parseDuration(""), SyntaxError);
});

test("formats durations", () => {
  assert.equal(formatDuration(5_400_000), "1h 30m");
  assert.equal(formatDuration(90_061_000), "1d 1h");
  assert.equal(formatDuration(42), "42ms");
});
