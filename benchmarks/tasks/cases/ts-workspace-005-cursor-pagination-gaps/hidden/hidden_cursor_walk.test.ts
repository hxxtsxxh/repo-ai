import { createApi } from "../../api/src/server.ts";
import { main } from "../../cli/src/main.ts";
import { memoryIo } from "../../cli/src/io.ts";
import { test } from "node:test";
import assert from "node:assert/strict";

const ADMIN = { authorization: "Bearer dev-admin-key" };

function seeded(n: number) {
  const api = createApi({ rateLimit: false, clock: () => new Date("2026-03-02T08:00:00Z") });
  for (let i = 1; i <= n; i++) {
    api.handle({ method: "POST", path: "/jobs", headers: ADMIN, body: { name: `job-${i}`, command: "x" } });
  }
  return api;
}

function walk(api: ReturnType<typeof createApi>, limit: number) {
  const seen: string[] = [];
  let cursor: string | null | undefined;
  let pages = 0;
  do {
    const query: Record<string, string> = { limit: String(limit) };
    if (cursor) query.cursor = cursor;
    const body = api.handle({ method: "GET", path: "/jobs", headers: ADMIN, query }).body as {
      items: Array<{ name: string }>; nextCursor: string | null;
    };
    seen.push(...body.items.map((j) => j.name));
    cursor = body.nextCursor;
    pages++;
  } while (cursor && pages < 20);
  return { seen, pages };
}

test("following cursors visits every job once", () => {
  assert.deepEqual(walk(seeded(5), 2), { seen: ["job-1", "job-2", "job-3", "job-4", "job-5"], pages: 3 });
  assert.deepEqual(walk(seeded(6), 3).seen, ["job-1", "job-2", "job-3", "job-4", "job-5", "job-6"]);
  assert.deepEqual(walk(seeded(6), 3).pages, 2);
});

test("regression: no cursor when everything fits; bad cursor is 400", () => {
  const api = seeded(3);
  const body = api.handle({ method: "GET", path: "/jobs", headers: ADMIN, query: { limit: "3" } }).body as { nextCursor: string | null };
  assert.equal(body.nextCursor, null);
  assert.equal(api.handle({ method: "GET", path: "/jobs", headers: ADMIN, query: { cursor: "zzz" } }).status, 400);
});

test("cli list --all", async () => {
  const api = seeded(5);
  const io = memoryIo();
  const code = await main(["list", "--all", "--limit", "2"], io, { api, apiKey: "dev-admin-key", now: () => new Date("2026-03-02T08:00:00Z") });
  assert.equal(code, 0);
  assert.equal(io.stdout.length, 6);
  assert.ok(io.stdout.some((l) => l.includes("job-3")));
});
