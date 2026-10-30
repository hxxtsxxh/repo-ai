import { test } from "node:test";
import assert from "node:assert/strict";
import type { Action, FormState } from "../src/job-form.ts";
import { canSubmit, initialState, reducer, toRequestBody, visibleError } from "../src/job-form.ts";

const VALID = { name: "nightly", command: "run.sh", schedule: "daily at 02:00", timeout: "10m" };
const DUP = "a queued job named nightly already exists";
const run = (state: FormState, ...actions: Action[]) => actions.reduce(reducer, state);

test("a rejected submit can be fixed and retried", () => {
  let s = run(initialState(VALID), { type: "submit" });
  assert.equal(s.status, "submitting");
  assert.equal(canSubmit(s), false);
  assert.equal(reducer(s, { type: "submit" }).submitCount, 1, "no double submit while in flight");
  s = reducer(s, { type: "submitFailed", message: DUP, fieldErrors: { name: DUP } });
  assert.equal(s.status, "failed");
  assert.equal(canSubmit(s), true);
  assert.equal(s.formError, DUP);
  assert.equal(visibleError(s, "name"), DUP);
  s = reducer(s, { type: "submit" });
  assert.equal(s.status, "submitting");
  assert.equal(s.submitCount, 2);
  assert.deepEqual(s.serverErrors, {});
  assert.equal(s.formError, null);
});

test("a failure without field details also unlocks the form", () => {
  let s = run(initialState(VALID), { type: "submit" }, { type: "submitFailed", message: "internal error" });
  assert.equal(s.status, "failed");
  assert.equal(canSubmit(s), true);
  assert.equal(s.formError, "internal error");
  s = reducer(s, { type: "change", field: "command", value: "run2.sh" });
  assert.equal(s.values.command, "run2.sh");
  assert.equal(canSubmit(s), true);
});

test("server errors stay with their field until that field changes", () => {
  let s = run(
    initialState(VALID),
    { type: "submit" },
    { type: "submitFailed", message: "invalid job", fieldErrors: { name: DUP, schedule: "unsupported on this runner" } },
  );
  s = reducer(s, { type: "change", field: "command", value: "run2.sh" });
  assert.equal(visibleError(s, "name"), DUP);
  assert.equal(visibleError(s, "schedule"), "unsupported on this runner");
  s = reducer(s, { type: "change", field: "name", value: "nightly-2" });
  assert.equal(visibleError(s, "name"), null);
  assert.equal(visibleError(s, "schedule"), "unsupported on this runner");
  s = reducer(s, { type: "change", field: "schedule", value: "daily at 03:00" });
  assert.equal(visibleError(s, "schedule"), null);
});

test("regression: client validation visibility", () => {
  let s = initialState();
  assert.equal(visibleError(s, "name"), null);
  assert.equal(canSubmit(s), false);
  s = reducer(s, { type: "blur", field: "name" });
  assert.match(visibleError(s, "name") ?? "", /lowercase/);
  assert.equal(visibleError(s, "command"), null);
  s = run(s, { type: "change", field: "timeout", value: "soon" }, { type: "submit" });
  assert.equal(s.status, "editing");
  assert.equal(s.submitCount, 1);
  assert.ok(visibleError(s, "command"));
  assert.ok(visibleError(s, "timeout"));
});

test("regression: success resets the form", () => {
  let s = run(initialState(VALID), { type: "submit" }, { type: "submitSucceeded" });
  assert.equal(s.status, "succeeded");
  assert.equal(s.values.name, "");
  s = reducer(s, { type: "change", field: "name", value: "next" });
  assert.equal(s.status, "editing");
  assert.deepEqual(toRequestBody(VALID), { name: "nightly", command: "run.sh", schedule: "daily at 02:00", timeout: "10m" });
});
