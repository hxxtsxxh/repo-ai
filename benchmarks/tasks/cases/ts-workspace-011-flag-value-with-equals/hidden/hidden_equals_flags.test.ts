import { test } from "node:test";
import assert from "node:assert/strict";
import { createApi } from "../../api/src/server.ts";
import { parseArgs } from "../src/args.ts";
import { main } from "../src/main.ts";
import { memoryIo } from "../src/io.ts";

test("only the first = separates name and value", () => {
  const args = parseArgs(["create", "backup", "--command=env MODE=full ./backup.sh", "--tag=a=b,c"]);
  assert.equal(args.flags.command, "env MODE=full ./backup.sh");
  assert.equal(args.flags.tag, "a=b,c");
  assert.equal(parseArgs(["x", "--empty="]).flags.empty, "");
});

test("cli stores the full command", async () => {
  const api = createApi({ rateLimit: false });
  const io = memoryIo();
  const code = await main(["create", "backup", "--command=env MODE=full ./backup.sh"], io, { api, apiKey: "dev-admin-key" });
  assert.equal(code, 0);
  assert.equal(api.store.get("job_0001")?.command, "env MODE=full ./backup.sh");
});

test("regression: other flag forms", () => {
  const args = parseArgs(["list", "--status", "failed", "--limit=5", "-a", "--no-color"]);
  assert.deepEqual(args.flags, { status: "failed", limit: "5", all: true, color: false });
});
