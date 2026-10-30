import { test } from "node:test";
import assert from "node:assert/strict";
import { createApi } from "../src/server.ts";
import { hasScope } from "../src/auth.ts";

const READER = { authorization: "Bearer dev-reader-key" };
const WRITER = { authorization: "Bearer dev-writer-key" };
const ADMIN = { authorization: "Bearer dev-admin-key" };

test("read-only key cannot change jobs", () => {
  const api = createApi({ rateLimit: false });
  assert.equal(api.handle({ method: "POST", path: "/jobs", headers: READER, body: { name: "a", command: "x" } }).status, 403);
  const created = api.handle({ method: "POST", path: "/jobs", headers: WRITER, body: { name: "a", command: "x" } });
  assert.equal(created.status, 201);
  const id = (created.body as { id: string }).id;
  assert.equal(api.handle({ method: "POST", path: `/jobs/${id}/cancel`, headers: READER }).status, 403);
  api.store.setStatus(id, "failed");
  assert.equal(api.handle({ method: "POST", path: `/jobs/${id}/retry`, headers: READER }).status, 403);
  assert.equal(api.handle({ method: "POST", path: `/jobs/${id}/retry`, headers: ADMIN }).status, 200);
});

test("hasScope", () => {
  const reader = { name: "r", key: "k", scopes: ["jobs:read" as const] };
  assert.equal(hasScope(reader, "jobs:read"), true);
  assert.equal(hasScope(reader, "jobs:write"), false);
  assert.equal(hasScope({ name: "a", key: "k", scopes: ["admin"] }, "jobs:write"), true);
});

test("regression: reader can still read", () => {
  const api = createApi({ rateLimit: false });
  assert.equal(api.handle({ method: "GET", path: "/jobs", headers: READER }).status, 200);
});
