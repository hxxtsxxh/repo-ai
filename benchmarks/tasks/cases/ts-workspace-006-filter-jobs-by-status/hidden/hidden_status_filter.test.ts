import { createApi } from "../../api/src/server.ts";
import { main } from "../../cli/src/main.ts";
import { memoryIo } from "../../cli/src/io.ts";
import { test } from "node:test";
import assert from "node:assert/strict";

const ADMIN = { authorization: "Bearer dev-admin-key" };
const NOW = () => new Date("2026-03-02T08:00:00Z");

function seeded() {
  const api = createApi({ rateLimit: false, clock: NOW });
  const make = (name: string, tags: string[]) =>
    (api.handle({ method: "POST", path: "/jobs", headers: ADMIN, body: { name, command: "x", tags } }).body as { id: string }).id;
  const a = make("alpha", ["nightly"]);
  const b = make("bravo", ["nightly"]);
  const c = make("charlie", ["adhoc"]);
  const d = make("delta", ["nightly"]);
  api.store.setStatus(b, "failed", { lastError: "boom" });
  api.store.setStatus(d, "failed");
  api.handle({ method: "POST", path: `/jobs/${c}/cancel`, headers: ADMIN });
  return { api, ids: { a, b, c, d } };
}

const names = (res: { body: unknown }) => (res.body as { items: Array<{ name: string }> }).items.map((j) => j.name);
const list = (api: ReturnType<typeof createApi>, query: Record<string, string>) =>
  api.handle({ method: "GET", path: "/jobs", headers: ADMIN, query });

test("single and multiple statuses", () => {
  const { api } = seeded();
  assert.deepEqual(names(list(api, { status: "failed" })), ["bravo", "delta"]);
  assert.deepEqual(names(list(api, { status: "failed,cancelled" })), ["bravo", "charlie", "delta"]);
  assert.deepEqual(names(list(api, { status: "queued" })), ["alpha"]);
});

test("combines with tag and pagination", () => {
  const { api } = seeded();
  assert.deepEqual(names(list(api, { status: "failed,cancelled", tag: "nightly" })), ["bravo", "delta"]);
  const first = list(api, { status: "failed,cancelled", limit: "2" });
  assert.deepEqual(names(first), ["bravo", "charlie"]);
  const cursor = (first.body as { nextCursor: string }).nextCursor;
  assert.deepEqual(names(list(api, { status: "failed,cancelled", limit: "2", cursor })), ["delta"]);
});

test("unknown status is 400", () => {
  const { api } = seeded();
  assert.equal(list(api, { status: "failed,bogus" }).status, 400);
});

test("regression: no filter lists everything", () => {
  const { api } = seeded();
  assert.equal(names(list(api, {})).length, 4);
});

test("cli list --status", async () => {
  const { api } = seeded();
  const io = memoryIo();
  const code = await main(["list", "--status", "cancelled"], io, { api, apiKey: "dev-admin-key", now: NOW });
  assert.equal(code, 0);
  assert.equal(io.stdout.length, 2);
  assert.match(io.stdout[1], /charlie\s+CANCELLED/);
});
