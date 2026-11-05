import { createApi } from "../../api/src/server.ts";
import { main } from "../../cli/src/main.ts";
import { memoryIo } from "../../cli/src/io.ts";
import { test } from "node:test";
import assert from "node:assert/strict";
import { nextRun, parseSchedule } from "../src/schedule.ts";

test("daily run exactly at the scheduled minute moves to tomorrow", () => {
  const s = parseSchedule("daily at 09:30");
  assert.equal(nextRun(s, new Date("2026-03-02T09:30:00.000Z")).toISOString(), "2026-03-03T09:30:00.000Z");
  assert.equal(nextRun(s, new Date("2026-03-02T09:29:59.999Z")).toISOString(), "2026-03-02T09:30:00.000Z");
});

test("regression: weekly and interval", () => {
  const w = parseSchedule("weekly on mon at 08:00");
  assert.equal(nextRun(w, new Date("2026-03-02T08:00:00Z")).toISOString(), "2026-03-09T08:00:00.000Z");
  const i = parseSchedule("every 90s");
  assert.equal(nextRun(i, new Date("2026-03-02T08:00:00Z")).toISOString(), "2026-03-02T08:01:30.000Z");
});

test("cli next from the scheduled time", async () => {
  const io = memoryIo();
  const code = await main(["next", "daily at 02:00", "--from", "2026-03-02T02:00:00Z", "--count", "2"], io,
    { api: createApi({ rateLimit: false }) });
  assert.equal(code, 0);
  assert.deepEqual(io.stdout, ["2026-03-03T02:00:00.000Z", "2026-03-04T02:00:00.000Z"]);
});
