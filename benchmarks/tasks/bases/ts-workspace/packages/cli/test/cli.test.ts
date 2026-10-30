import { test } from "node:test";
import assert from "node:assert/strict";
import { createApi } from "../../api/src/server.ts";
import { main } from "../src/main.ts";
import { memoryIo } from "../src/io.ts";
import { parseArgs } from "../src/args.ts";
import { renderTable } from "../src/table.ts";

const NOW = new Date("2026-03-02T08:00:00Z");

function harness() {
  const api = createApi({ clock: () => NOW, rateLimit: false });
  const run = async (...argv: string[]) => {
    const io = memoryIo();
    const code = await main(argv, io, { api, apiKey: "dev-admin-key", now: () => NOW });
    return { code, out: io.stdout, err: io.stderr };
  };
  return { api, run };
}

test("parses flags and positionals", () => {
  const args = parseArgs(["create", "nightly", "--command", "run.sh", "--timeout=5m", "-v", "--no-color"]);
  assert.equal(args.command, "create");
  assert.deepEqual(args.positionals, ["nightly"]);
  assert.deepEqual(args.flags, { command: "run.sh", timeout: "5m", verbose: true, color: false });
});

test("renders aligned tables", () => {
  const lines = renderTable([{ header: "A", value: (r: string) => r }, { header: "B", value: () => "x" }], ["long"]);
  assert.deepEqual(lines, ["A     B", "long  x"]);
});

test("create then list", async () => {
  const { run } = harness();
  const created = await run("create", "nightly", "--command", "run.sh", "--schedule", "daily at 09:30", "--timeout", "10m");
  assert.equal(created.code, 0);
  assert.match(created.out[0], /^Created job_0001/);
  const listed = await run("list");
  assert.equal(listed.code, 0);
  assert.match(listed.out[0], /^ID\s+NAME\s+STATUS/);
  assert.match(listed.out[1], /nightly\s+QUEUED\s+daily at 09:30\s+in 1h\s+10m/);
});

test("unknown job exits 3", async () => {
  const { run } = harness();
  const res = await run("show", "job_0404");
  assert.equal(res.code, 3);
  assert.match(res.err[0], /not found/);
});

test("next previews schedule", async () => {
  const { run } = harness();
  const res = await run("next", "every", "2h", "--count", "2");
  assert.deepEqual(res.out, ["2026-03-02T10:00:00.000Z", "2026-03-02T12:00:00.000Z"]);
});

test("cancel prints new status", async () => {
  const { run } = harness();
  await run("create", "a", "--command", "x");
  const res = await run("cancel", "job_0001");
  assert.equal(res.out[0], "Cancelled job_0001 (now CANCELLED)");
});
