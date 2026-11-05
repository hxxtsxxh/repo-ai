// Mutation check: the core package's own tests must reject broken truncate() variants.
import { test } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { cpSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const SELF = fileURLToPath(import.meta.url);
const CORE = join(dirname(SELF), "..");
const PACKAGES = join(CORE, "..");

const ORIGINAL = `export function truncate(text: string, width: number): string {
  if (width <= 0) return "";
  const chars = Array.from(text);
  if (chars.length <= width) return text;
  if (width === 1) return ELLIPSIS;
  return chars.slice(0, width - 1).join("") + ELLIPSIS;
}`;

const MUTANTS: Record<string, string> = {
  "off by one": `export function truncate(text: string, width: number): string {
  if (width <= 0) return "";
  const chars = Array.from(text);
  if (chars.length <= width) return text;
  if (width === 1) return ELLIPSIS;
  return chars.slice(0, width).join("") + ELLIPSIS;
}`,
  "utf-16 length": `export function truncate(text: string, width: number): string {
  if (width <= 0) return "";
  if (text.length <= width) return text;
  if (width === 1) return ELLIPSIS;
  return text.slice(0, width - 1) + ELLIPSIS;
}`,
  "exact fit truncated": `export function truncate(text: string, width: number): string {
  if (width <= 0) return "";
  const chars = Array.from(text);
  if (chars.length < width) return text;
  if (width === 1) return ELLIPSIS;
  return chars.slice(0, width - 1).join("") + ELLIPSIS;
}`,
  "non-positive width": `export function truncate(text: string, width: number): string {
  const chars = Array.from(text);
  if (chars.length <= width) return text;
  if (width <= 1) return ELLIPSIS;
  return chars.slice(0, width - 1).join("") + ELLIPSIS;
}`,
};

function runCoreTests(mutant: string | null): { status: number | null; output: string } {
  const dir = mkdtempSync(join(tmpdir(), "core-mut-"));
  try {
    cpSync(PACKAGES, join(dir, "packages"), {
      recursive: true,
      filter: (src) => !basename(src).startsWith("hidden_"),
    });
    const testDir = join(dir, "packages", "core", "test");
    const stringsPath = join(dir, "packages", "core", "src", "strings.ts");
    if (mutant !== null) {
      const source = readFileSync(stringsPath, "utf8");
      assert.ok(source.includes(ORIGINAL), "packages/core/src/strings.ts truncate() was modified; it must stay as is");
      writeFileSync(stringsPath, source.replace(ORIGINAL, mutant));
    }
    const files = readdirSync(testDir).filter((f) => f.endsWith(".test.ts")).map((f) => join(testDir, f));
    const env = { ...process.env };
    delete env.NODE_TEST_CONTEXT;
    const proc = spawnSync(process.execPath, ["--test", ...files], { cwd: join(dir, "packages", "core"), env, encoding: "utf8", timeout: 60_000 });
    return { status: proc.status, output: `${proc.stdout}\n${proc.stderr}` };
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

test("core tests pass against the real implementation", () => {
  const { status, output } = runCoreTests(null);
  assert.equal(status, 0, output.slice(-1500));
});

for (const [name, mutant] of Object.entries(MUTANTS)) {
  test(`core tests catch truncate mutant: ${name}`, () => {
    const { status } = runCoreTests(mutant);
    assert.notEqual(status, 0, `the core test suite did not notice the "${name}" mutant`);
  });
}
