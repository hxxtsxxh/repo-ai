import { test } from "node:test";
import assert from "node:assert/strict";
import { createApi } from "../../api/src/server.ts";
import { main } from "../src/main.ts";
import { memoryIo } from "../src/io.ts";

async function create(...flags: string[]) {
  const api = createApi({ rateLimit: false });
  const io = memoryIo();
  const code = await main(["create", "nightly", "--command", "backup.sh", ...flags], io, { api, apiKey: "dev-admin-key" });
  return { code, io, job: api.store.get("job_0001") };
}

test("accepts the full duration syntax", async () => {
  let r = await create("--timeout", "2h");
  assert.equal(r.code, 0, r.io.stderr.join("\n"));
  assert.equal(r.job?.timeoutMs, 7_200_000);
  r = await create("--backoff", "1m30s");
  assert.equal(r.job?.retry.backoffMs, 90_000);
  r = await create("--timeout", "250ms");
  assert.equal(r.job?.timeoutMs, 250);
  r = await create("--timeout", "15");
  assert.equal(r.job?.timeoutMs, 15_000);
});

test("invalid durations still exit 2", async () => {
  const r = await create("--timeout", "soon");
  assert.equal(r.code, 2);
  assert.match(r.io.stderr[0], /--timeout/);
  assert.equal(r.job, undefined);
});

test("regression: minutes", async () => {
  const r = await create("--timeout", "10m");
  assert.equal(r.job?.timeoutMs, 600_000);
});
