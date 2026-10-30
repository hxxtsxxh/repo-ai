import { test } from "node:test";
import assert from "node:assert/strict";
import { ADMIN, READER, setup } from "./helpers.ts";

function create(api: ReturnType<typeof setup>["api"], body: Record<string, unknown>) {
  return api.handle({ method: "POST", path: "/jobs", headers: ADMIN, body });
}

test("health needs no key", () => {
  const { api } = setup();
  assert.equal(api.handle({ method: "GET", path: "/health" }).status, 200);
});

test("creates and fetches a job", () => {
  const { api } = setup();
  const res = create(api, { name: "nightly", command: "run.sh", schedule: "daily at 09:30", timeout: "10m" });
  assert.equal(res.status, 201);
  const body = res.body as { id: string; timeout: string; nextRunAt: string };
  assert.equal(body.timeout, "10m");
  assert.equal(body.nextRunAt, "2026-03-02T09:30:00.000Z");
  assert.equal(res.headers.location, `/jobs/${body.id}`);
  const got = api.handle({ method: "GET", path: `/jobs/${body.id}`, headers: READER });
  assert.equal(got.status, 200);
});

test("validation errors are 400", () => {
  const { api } = setup();
  const res = create(api, { name: "Bad Name!", command: "" });
  assert.equal(res.status, 400);
});

test("unknown key is 401 and unknown job is 404", () => {
  const { api } = setup();
  assert.equal(api.handle({ method: "GET", path: "/jobs", headers: { authorization: "Bearer nope" } }).status, 401);
  assert.equal(api.handle({ method: "GET", path: "/jobs/job_9999", headers: ADMIN }).status, 404);
});

test("reader key can list via x-api-key", () => {
  const { api } = setup();
  create(api, { name: "a", command: "x" });
  const res = api.handle({ method: "GET", path: "/jobs", headers: { "x-api-key": "dev-reader-key" } });
  assert.equal(res.status, 200);
  assert.equal((res.body as { items: unknown[] }).items.length, 1);
});

test("cancel then cancel again conflicts", () => {
  const { api } = setup();
  const id = (create(api, { name: "a", command: "x" }).body as { id: string }).id;
  assert.equal(api.handle({ method: "POST", path: `/jobs/${id}/cancel`, headers: ADMIN }).status, 200);
  assert.equal(api.handle({ method: "POST", path: `/jobs/${id}/cancel`, headers: ADMIN }).status, 409);
});

test("lists jobs with first page", () => {
  const { api } = setup();
  for (const name of ["a", "b", "c"]) create(api, { name, command: "x" });
  const res = api.handle({ method: "GET", path: "/jobs", headers: ADMIN, query: { limit: "2" } });
  const body = res.body as { items: Array<{ name: string }>; nextCursor: string | null };
  assert.deepEqual(body.items.map((j) => j.name), ["a", "b"]);
  assert.notEqual(body.nextCursor, null);
});

test("outdated clients are rejected", () => {
  const { api } = setup();
  const res = api.handle({ method: "GET", path: "/jobs", headers: { ...ADMIN, "x-client-version": "1.1.0" } });
  assert.equal(res.status, 426);
  const ok = api.handle({ method: "GET", path: "/jobs", headers: { ...ADMIN, "x-client-version": "1.6.2" } });
  assert.equal(ok.status, 200);
});

test("method not allowed", () => {
  const { api } = setup();
  const res = api.handle({ method: "DELETE", path: "/jobs", headers: ADMIN });
  assert.equal(res.status, 405);
});
