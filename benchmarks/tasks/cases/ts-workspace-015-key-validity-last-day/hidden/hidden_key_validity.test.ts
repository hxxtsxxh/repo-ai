import { test } from "node:test";
import assert from "node:assert/strict";
import { createApi } from "../src/server.ts";
import type { KeyTable } from "../src/auth.ts";
import { main } from "../../cli/src/main.ts";
import { memoryIo } from "../../cli/src/io.ts";
import { daysLeft, isExpired } from "../../core/src/dates.ts";

const KEYS: KeyTable = {
  "k-today": { name: "partner-today", scopes: ["jobs:read"], validUntil: "2026-03-02" },
  "k-month": { name: "partner-month", scopes: ["jobs:read"], validUntil: "2026-03-31" },
  "k-tomorrow": { name: "partner-tomorrow", scopes: ["jobs:read"], validUntil: "2026-03-03" },
  "k-gone": { name: "partner-gone", scopes: ["jobs:read"], validUntil: "2026-03-01" },
  "k-forever": { name: "internal", scopes: ["admin"] },
};

function harness(iso: string) {
  let now = new Date(iso).getTime();
  const clock = () => new Date(now);
  const api = createApi({ keys: KEYS, clock, rateLimit: false });
  const get = (key: string, path = "/jobs") => api.handle({ method: "GET", path, headers: { authorization: `Bearer ${key}` } });
  const cli = async (key: string) => {
    const io = memoryIo();
    const code = await main(["whoami"], io, { api, apiKey: key, now: clock });
    return { code, out: io.stdout, err: io.stderr };
  };
  return { api, get, cli, set: (next: string) => void (now = new Date(next).getTime()) };
}

test("a key works for the whole of its last day", () => {
  const h = harness("2026-03-02T08:00:00Z");
  assert.equal(h.get("k-today").status, 200);
  h.set("2026-03-02T00:00:00Z");
  assert.equal(h.get("k-today").status, 200);
  h.set("2026-03-02T23:59:59.999Z");
  assert.equal(h.get("k-today").status, 200);
  h.set("2026-03-03T00:00:00Z");
  const res = h.get("k-today");
  assert.equal(res.status, 401);
  assert.match(JSON.stringify(res.body), /expired/);
});

test("keys past their date are rejected", () => {
  const h = harness("2026-03-02T08:00:00Z");
  assert.equal(h.get("k-gone").status, 401);
  assert.equal(h.get("k-forever").status, 200);
});

test("whoami reports calendar days left", () => {
  const h = harness("2026-03-02T08:00:00Z");
  const month = h.get("k-month", "/auth/whoami").body as { daysLeft: number; validUntil: string };
  assert.equal(month.daysLeft, 29);
  assert.equal(month.validUntil, "2026-03-31");
  assert.equal((h.get("k-today", "/auth/whoami").body as { daysLeft: number }).daysLeft, 0);
  assert.equal((h.get("k-tomorrow", "/auth/whoami").body as { daysLeft: number }).daysLeft, 1);
  assert.equal((h.get("k-forever", "/auth/whoami").body as { daysLeft: null }).daysLeft, null);
  h.set("2026-03-02T23:30:00Z");
  assert.equal((h.get("k-tomorrow", "/auth/whoami").body as { daysLeft: number }).daysLeft, 1);
  assert.equal((h.get("k-month", "/auth/whoami").body as { daysLeft: number }).daysLeft, 29);
});

test("cli whoami wording", async () => {
  const h = harness("2026-03-02T08:00:00Z");
  const month = await h.cli("k-month");
  assert.equal(month.code, 0);
  assert.deepEqual(month.out, ["partner-month (jobs:read)", "key expires in 29 days (2026-03-31)"]);
  const today = await h.cli("k-today");
  assert.equal(today.code, 0);
  assert.equal(today.out[1], "key expires today (2026-03-02)");
  const tomorrow = await h.cli("k-tomorrow");
  assert.equal(tomorrow.out[1], "key expires in 1 day (2026-03-03)");
  const forever = await h.cli("k-forever");
  assert.equal(forever.out[1], "key does not expire");
  const gone = await h.cli("k-gone");
  assert.equal(gone.code, 4);
});

test("core date helpers", () => {
  assert.equal(isExpired("2026-03-02", new Date("2026-03-02T12:00:00Z")), false);
  assert.equal(isExpired("2026-03-02", new Date("2026-03-03T00:00:00Z")), true);
  assert.equal(isExpired("2024-02-29", new Date("2024-02-29T23:00:00Z")), false);
  assert.equal(daysLeft("2026-03-03", new Date("2026-03-02T23:00:00Z")), 1);
  assert.equal(daysLeft("2026-04-01", new Date("2026-03-31T00:00:00Z")), 1);
  assert.equal(daysLeft("2027-03-02", new Date("2026-03-02T15:00:00Z")), 365);
});
