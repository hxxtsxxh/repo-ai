import { test } from "node:test";
import assert from "node:assert/strict";
import { describeSchedule, nextRun, parseSchedule } from "../src/schedule.ts";

test("parses interval schedules", () => {
  assert.deepEqual(parseSchedule("every 15m"), { kind: "interval", everyMs: 900_000 });
});

test("parses daily and weekly schedules", () => {
  assert.deepEqual(parseSchedule("daily at 09:30"), { kind: "daily", hour: 9, minute: 30 });
  assert.deepEqual(parseSchedule("Weekly on MON at 08:00"), { kind: "weekly", weekday: 1, hour: 8, minute: 0 });
});

test("daily next run later the same day or tomorrow", () => {
  const s = parseSchedule("daily at 09:30");
  assert.equal(nextRun(s, new Date("2026-03-02T08:00:00Z")).toISOString(), "2026-03-02T09:30:00.000Z");
  assert.equal(nextRun(s, new Date("2026-03-02T10:00:00Z")).toISOString(), "2026-03-03T09:30:00.000Z");
});

test("weekly next run", () => {
  const s = parseSchedule("weekly on fri at 17:00");
  assert.equal(nextRun(s, new Date("2026-03-02T08:00:00Z")).toISOString(), "2026-03-06T17:00:00.000Z");
});

test("describes schedules", () => {
  assert.equal(describeSchedule(parseSchedule("daily 7:05")), "daily at 07:05 UTC");
});
