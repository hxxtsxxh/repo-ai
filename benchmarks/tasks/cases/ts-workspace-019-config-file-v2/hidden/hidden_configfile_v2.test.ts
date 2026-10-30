import { test } from "node:test";
import assert from "node:assert/strict";
import * as configfile from "../src/configfile.ts";
import { resolveConfig } from "../src/config.ts";

const { ConfigFileError, parseConfigFile } = configfile;
const upgradeConfigFile = (text: string): string => {
  assert.equal(typeof configfile.upgradeConfigFile, "function", "upgradeConfigFile is not exported");
  return configfile.upgradeConfigFile(text);
};

const V2 = JSON.stringify({
  version: 2,
  runner: { concurrency: 8, defaultTimeout: "2m" },
  retry: { maxAttempts: 5 },
  api: { port: 9000 },
  logging: { level: "debug" },
});
const V1 = JSON.stringify({ logLevel: "debug", timeout: "2m", concurrency: 8, port: 9000, maxAttempts: 5 });
const EXPECTED = { concurrency: 8, defaultTimeoutMs: 120_000, maxAttempts: 5, apiPort: 9000, logLevel: "debug" };

function collect() {
  const messages: string[] = [];
  return { messages, warn: (m: string) => void messages.push(m) };
}

test("format 2 parses without warnings", () => {
  const w = collect();
  assert.deepEqual(parseConfigFile(V2, w), EXPECTED);
  assert.deepEqual(w.messages, []);
  assert.deepEqual(parseConfigFile('{"version": 2, "logging": {"level": "WARN"}}', w), { logLevel: "warn" });
  assert.deepEqual(parseConfigFile('{"version": 2}', w), {});
  assert.equal(resolveConfig({ file: parseConfigFile(V2, w) }).apiPort, 9000);
});

test("format 1 still works but is deprecated", () => {
  const w = collect();
  assert.deepEqual(parseConfigFile(V1, w), EXPECTED);
  assert.equal(w.messages.length, 1);
  assert.match(w.messages[0], /deprecat/i);
});

test("bad versions, sections and keys are rejected", () => {
  const w = collect();
  for (const text of [
    '{"version": 3}',
    '{"version": "2"}',
    '{"version": 2, "scheduler": {"threads": 2}}',
    '{"version": 2, "runner": {"threads": 2}}',
    '{"version": 2, "runner": 4}',
    '{"version": 2, "api": {"port": "9000"}}',
    '{"threads": 2}',
    "[1, 2]",
    "{nope",
  ]) {
    assert.throws(() => parseConfigFile(text, w), ConfigFileError, text);
  }
  assert.throws(() => parseConfigFile('{"version": 3}', w), /3/);
});

test("upgrade produces canonical format 2", () => {
  const out = upgradeConfigFile('{"logLevel": "DEBUG", "timeout": "2m", "concurrency": 8, "port": 9000}');
  assert.equal(
    out,
    [
      "{",
      '  "version": 2,',
      '  "runner": {',
      '    "concurrency": 8,',
      '    "defaultTimeout": "2m"',
      "  },",
      '  "api": {',
      '    "port": 9000',
      "  },",
      '  "logging": {',
      '    "level": "DEBUG"',
      "  }",
      "}",
      "",
    ].join("\n"),
  );
  const w = collect();
  assert.deepEqual(parseConfigFile(out, w), { concurrency: 8, defaultTimeoutMs: 120_000, apiPort: 9000, logLevel: "debug" });
  assert.deepEqual(w.messages, []);
  assert.equal(upgradeConfigFile(V1), upgradeConfigFile(V2));
  assert.equal(upgradeConfigFile("{}"), '{\n  "version": 2\n}\n');
  assert.throws(() => upgradeConfigFile('{"threads": 2}'), ConfigFileError);
  assert.throws(() => upgradeConfigFile('{"timeout": "soon"}'), ConfigFileError);
});
