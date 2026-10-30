import { createApi } from "../../api/src/server.ts";
import { main } from "../../cli/src/main.ts";
import { memoryIo } from "../../cli/src/io.ts";
import { test } from "node:test";
import assert from "node:assert/strict";
import { parseDuration } from "../src/duration.ts";

test("millisecond unit", () => {
  assert.equal(parseDuration("250ms"), 250);
  assert.equal(parseDuration("1s500ms"), 1500);
  assert.equal(parseDuration("1m 30s 20ms"), 90_020);
});

test("regression: other units", () => {
  assert.equal(parseDuration("1h30m"), 5_400_000);
  assert.equal(parseDuration("2d"), 172_800_000);
  assert.throws(() => parseDuration("5x"), SyntaxError);
});

test("api and cli accept ms", async () => {
  const api = createApi({ rateLimit: false });
  const res = api.handle({ method: "POST", path: "/jobs", headers: { authorization: "Bearer dev-admin-key" },
    body: { name: "fast", command: "x", timeout: "750ms" } });
  assert.equal(res.status, 201);
  assert.equal((res.body as { timeoutMs: number }).timeoutMs, 750);
  const io = memoryIo();
  const code = await main(["create", "ping", "--command", "ping.sh", "--timeout", "250ms"], io, { api, apiKey: "dev-admin-key" });
  assert.equal(code, 0, io.stderr.join("\n"));
  assert.equal(api.store.get("job_0002")?.timeoutMs, 250);
});
