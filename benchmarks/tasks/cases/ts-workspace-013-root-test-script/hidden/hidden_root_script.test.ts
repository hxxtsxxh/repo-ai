import { test } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");

test("root test script runs every package's tests", () => {
  const pkg = JSON.parse(readFileSync(join(ROOT, "package.json"), "utf8"));
  const script: string = pkg.scripts.test;
  const env: Record<string, string | undefined> = { ...process.env, PATH: `${dirname(process.execPath)}:${process.env.PATH ?? ""}` };
  delete env.NODE_TEST_CONTEXT;
  const proc = spawnSync("sh", ["-c", script], { cwd: ROOT, env, encoding: "utf8", timeout: 60_000 });
  const output = `${proc.stdout}\n${proc.stderr}`;
  assert.equal(proc.status, 0, output.slice(-2000));
  const count = /(?:ℹ|#) tests (\d+)/.exec(output);
  assert.ok(count, output.slice(-2000));
  assert.ok(Number(count[1]) >= 35, `only ${count[1]} tests ran`);
  for (const name of ["parses single units", "health needs no key", "create then list"]) {
    assert.ok(output.includes(name), `missing test "${name}" from output`);
  }
});
