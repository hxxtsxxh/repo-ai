import { test } from "node:test";
import assert from "node:assert/strict";
import { compareVersions, satisfies } from "../src/semver.ts";

test("compares versions", () => {
  assert.equal(compareVersions("1.2.3", "1.2.4"), -1);
  assert.equal(compareVersions("2.0.0", "1.9.9"), 1);
  assert.equal(compareVersions("1.0.0-beta", "1.0.0"), -1);
});

test("caret ranges on 1.x", () => {
  assert.equal(satisfies("1.4.2", "^1.2.0"), true);
  assert.equal(satisfies("2.0.0", "^1.2.0"), false);
});

test("tilde and comparators", () => {
  assert.equal(satisfies("1.2.9", "~1.2.3"), true);
  assert.equal(satisfies("1.3.0", "~1.2.3"), false);
  assert.equal(satisfies("1.5.0", ">=1.2.0 <2.0.0"), true);
  assert.equal(satisfies("3.0.0", "^1.0.0 || ^3.0.0"), true);
});
