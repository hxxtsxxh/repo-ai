import { createApi } from "../../api/src/server.ts";
import { main } from "../../cli/src/main.ts";
import { memoryIo } from "../../cli/src/io.ts";
import { test } from "node:test";
import assert from "node:assert/strict";
import { canTransition } from "../../core/src/lifecycle.ts";
import { JOB_STATUSES } from "../../core/src/types.ts";

const ADMIN = { authorization: "Bearer dev-admin-key" };
const READER = { authorization: "Bearer dev-reader-key" };
const WRITER = { authorization: "Bearer dev-writer-key" };
const NOW = () => new Date("2026-03-02T08:00:00Z");

function setup() {
  const api = createApi({ rateLimit: false, clock: NOW });
  const res = api.handle({ method: "POST", path: "/jobs", headers: ADMIN,
    body: { name: "nightly", command: "x", schedule: "daily at 09:30" } });
  return { api, id: (res.body as { id: string }).id };
}
const post = (api: ReturnType<typeof createApi>, path: string, headers = WRITER) =>
  api.handle({ method: "POST", path, headers });

test("core lifecycle knows paused", () => {
  assert.ok(JOB_STATUSES.includes("paused" as never));
  assert.equal(canTransition("queued", "paused"), true);
  assert.equal(canTransition("paused", "queued"), true);
  assert.equal(canTransition("paused", "cancelled"), true);
  assert.equal(canTransition("paused", "running"), false);
  assert.equal(canTransition("running", "paused"), false);
});

test("pause and resume over the API", () => {
  const { api, id } = setup();
  const paused = post(api, `/jobs/${id}/pause`);
  assert.equal(paused.status, 200);
  assert.equal((paused.body as { status: string }).status, "paused");
  assert.equal((paused.body as { nextRunAt: string | null }).nextRunAt, null);
  assert.equal(post(api, `/jobs/${id}/pause`).status, 409);
  const listed = api.handle({ method: "GET", path: "/jobs", headers: READER, query: { status: "paused" } });
  assert.equal(listed.status, 200);
  assert.equal((listed.body as { items: unknown[] }).items.length, 1);
  const resumed = post(api, `/jobs/${id}/resume`);
  assert.equal(resumed.status, 200);
  assert.equal((resumed.body as { status: string }).status, "queued");
  assert.equal(post(api, `/jobs/${id}/resume`).status, 409);
});

test("scopes and invalid transitions", () => {
  const { api, id } = setup();
  assert.equal(post(api, `/jobs/${id}/pause`, READER).status, 403);
  api.store.setStatus(id, "running");
  assert.equal(post(api, `/jobs/${id}/pause`).status, 409);
  assert.equal(post(api, "/jobs/job_9999/pause").status, 404);
});

test("paused job can be cancelled", () => {
  const { api, id } = setup();
  post(api, `/jobs/${id}/pause`);
  const res = post(api, `/jobs/${id}/cancel`);
  assert.equal(res.status, 200);
  assert.equal((res.body as { status: string }).status, "cancelled");
});

test("cli pause/resume", async () => {
  const { api, id } = setup();
  const run = async (...argv: string[]) => {
    const io = memoryIo();
    const code = await main(argv, io, { api, apiKey: "dev-admin-key", now: NOW });
    return { code, io };
  };
  let r = await run("pause", id);
  assert.equal(r.code, 0, r.io.stderr.join("\n"));
  assert.deepEqual(r.io.stdout, [`Paused ${id} (now PAUSED)`]);
  r = await run("resume", id);
  assert.deepEqual(r.io.stdout, [`Resumed ${id} (now QUEUED)`]);
  r = await run("cancel", id);
  assert.deepEqual(r.io.stdout, [`Cancelled ${id} (now CANCELLED)`]);
});
