import { test } from "node:test";
import assert from "node:assert/strict";
import { satisfies } from "../src/semver.ts";
import { createApi } from "../../api/src/server.ts";

test("caret on 0.x stays within the minor", () => {
  assert.equal(satisfies("0.9.5", "^0.9.2"), true);
  assert.equal(satisfies("0.10.0", "^0.9.2"), false);
  assert.equal(satisfies("0.12.0", "^1.4.0 || ^0.9.2"), false);
});

test("caret on 0.0.x stays within the patch", () => {
  assert.equal(satisfies("0.0.3", "^0.0.3"), true);
  assert.equal(satisfies("0.0.4", "^0.0.3"), false);
});

test("regression: caret on 1.x", () => {
  assert.equal(satisfies("1.9.9", "^1.2.0"), true);
  assert.equal(satisfies("2.0.0", "^1.2.0"), false);
});

test("api rejects 0.12 clients", () => {
  const api = createApi({ rateLimit: false });
  const call = (v: string) =>
    api.handle({ method: "GET", path: "/jobs", headers: { authorization: "Bearer dev-admin-key", "x-client-version": v } }).status;
  assert.equal(call("0.12.0"), 426);
  assert.equal(call("0.9.7"), 200);
  assert.equal(call("1.5.0"), 200);
});
