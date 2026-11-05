import { test } from "node:test";
import assert from "node:assert/strict";
import type { JobDto } from "../../api/src/serialize.ts";
import { truncate } from "../../core/src/strings.ts";
import { renderJobRow, renderJobsTable, sortJobs } from "../src/jobs-table.ts";

const NOW = new Date("2026-03-02T08:00:00Z");

function dto(id: string, overrides: Partial<JobDto> = {}): JobDto {
  return {
    id,
    name: id.replace("job_", "job-"),
    command: "run.sh",
    status: "queued",
    attempts: 0,
    schedule: null,
    scheduleDescription: null,
    nextRunAt: null,
    timeout: "1m",
    timeoutMs: 60_000,
    retry: { maxAttempts: 3, backoff: "1s", maxBackoff: "5m" },
    tags: [],
    createdAt: NOW.toISOString(),
    updatedAt: NOW.toISOString(),
    lastError: null,
    links: { self: `/jobs/${id}` },
    ...overrides,
  };
}

const NAMED: Record<string, string> = { amp: "&", lt: "<", gt: ">", quot: '"', "#39": "'", "#x27": "'", apos: "'" };
const unescape = (text: string) => text.replace(/&(amp|lt|gt|quot|#39|#x27|apos);/g, (_, e: string) => NAMED[e]);

function commandCell(html: string): { tag: string; text: string } {
  const match = /(<td[^>]*class="command"[^>]*>)(.*?)<\/td>/s.exec(html);
  assert.ok(match, `no command cell in ${html}`);
  return { tag: match[1], text: match[2] };
}

function assertWellFormed(text: string) {
  for (const m of text.matchAll(/&[^;\s<&]*;?/g)) {
    assert.match(m[0], /^&(amp|lt|gt|quot|#39|#x27|apos);$/, `broken entity in ${JSON.stringify(text)}`);
  }
  assert.ok(!/[<>"]/.test(text), `raw markup in ${JSON.stringify(text)}`);
}

const COMMANDS = [
  "make backup && notify <ops@example.com>",
  'report.sh --title "Q1 & Q2" --to finance',
  "a&&b&&c&&d&&e&&f&&g&&h&&i&&j&&k&&l&&m",
  "echo '<b>bold</b>' > /tmp/out.html",
];

test("commands are cut by visible characters and shown literally", () => {
  for (const command of COMMANDS) {
    for (let width = 4; width <= 44; width++) {
      const html = renderJobRow(dto("job_0001", { command }), { now: NOW, commandWidth: width });
      const { text } = commandCell(html);
      assertWellFormed(text);
      assert.equal(unescape(text), truncate(command, width), `width ${width}: ${text}`);
    }
  }
});

test("tooltip keeps the full command", () => {
  const command = COMMANDS[1];
  const { tag } = commandCell(renderJobRow(dto("job_0001", { command }), { now: NOW, commandWidth: 10 }));
  const title = /title="([^"]*)"/.exec(tag);
  assert.ok(title);
  assert.equal(unescape(title[1]), command);
});

test("short commands are untouched", () => {
  const { text } = commandCell(renderJobRow(dto("job_0001", { command: "echo hi" }), { now: NOW }));
  assert.equal(text, "echo hi");
});

const JOBS = [
  dto("job_0001", { nextRunAt: "2026-03-02T10:00:00.000Z" }),
  dto("job_0002", { nextRunAt: null, status: "cancelled" }),
  dto("job_0003", { nextRunAt: "2026-03-02T09:00:00.000Z" }),
  dto("job_0004", { nextRunAt: null, status: "failed" }),
  dto("job_0005", { nextRunAt: "2026-03-02T12:00:00.000Z" }),
];

const rowIds = (html: string) => [...html.matchAll(/<tr data-id="([^"]+)"/g)].map((m) => m[1]);

test("jobs without a next run sort last in both directions", () => {
  const asc = { key: "nextRunAt" as const, dir: "asc" as const };
  const desc = { key: "nextRunAt" as const, dir: "desc" as const };
  assert.deepEqual(sortJobs(JOBS, asc).map((j) => j.id), ["job_0003", "job_0001", "job_0005", "job_0002", "job_0004"]);
  assert.deepEqual(sortJobs(JOBS, desc).map((j) => j.id), ["job_0005", "job_0001", "job_0003", "job_0002", "job_0004"]);
  assert.deepEqual(rowIds(renderJobsTable(JOBS, { now: NOW, sort: asc })), ["job_0003", "job_0001", "job_0005", "job_0002", "job_0004"]);
});

test("regressions: other sorts, empty state, footer, selection", () => {
  const byName = sortJobs(
    [dto("job_0002", { name: "beta" }), dto("job_0001", { name: "alpha" }), dto("job_0003", { name: "alpha" })],
    { key: "name", dir: "desc" },
  );
  assert.deepEqual(byName.map((j) => j.id), ["job_0002", "job_0001", "job_0003"]);
  assert.deepEqual(sortJobs(JOBS).map((j) => j.id), JOBS.map((j) => j.id));
  assert.match(renderJobsTable([], { now: NOW }), /No jobs match/);
  const html = renderJobsTable(JOBS, { now: NOW, selectedId: "job_0003", sort: { key: "status", dir: "asc" } });
  assert.match(html, /5 jobs/);
  assert.match(html, /<tr data-id="job_0003" class="selected" aria-selected="true">/);
  assert.match(html, /aria-sort="ascending">Status/);
  assert.match(html, /in 1h/);
});
