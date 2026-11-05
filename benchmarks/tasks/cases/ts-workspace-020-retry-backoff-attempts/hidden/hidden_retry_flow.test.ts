import { test } from "node:test";
import assert from "node:assert/strict";
import { ADMIN, setup } from "./helpers.ts";
import { nextAttemptAt } from "../../core/src/retry.ts";

interface Dto {
  id: string;
  status: string;
  attempts: number;
  retryAt: string | null;
  nextRunAt: string | null;
  lastError: string | null;
}

const T0 = Date.parse("2026-03-02T08:00:00Z");
const at = (ms: number) => new Date(T0 + ms).toISOString();

function harness(body: Record<string, unknown>) {
  const { api, clock } = setup();
  const created = api.handle({ method: "POST", path: "/jobs", headers: ADMIN, body });
  assert.equal(created.status, 201);
  const id = (created.body as Dto).id;
  const call = (verb: string, payload?: unknown) =>
    api.handle({ method: "POST", path: `/jobs/${id}/${verb}`, headers: ADMIN, body: payload });
  const get = () => api.handle({ method: "GET", path: `/jobs/${id}`, headers: ADMIN }).body as Dto;
  return { clock, call, get };
}

test("maxAttempts counts every run; first retry waits the base backoff", () => {
  const h = harness({ name: "sync", command: "sync.sh", retry: { maxAttempts: 3, backoff: "1s", maxBackoff: "5m" } });
  assert.equal((h.call("start").body as Dto).attempts, 1);
  let job = h.call("fail", { error: "exit 1" }).body as Dto;
  assert.equal(job.status, "queued");
  assert.equal(job.retryAt, at(1000));
  assert.equal(job.lastError, "exit 1");
  assert.equal(h.call("start").status, 409, "must wait for the backoff");
  h.clock.advance(1000);
  assert.equal((h.call("start").body as Dto).attempts, 2);
  job = h.call("fail", { error: "exit 2" }).body as Dto;
  assert.equal(job.retryAt, at(1000 + 2000));
  h.clock.advance(2000);
  assert.equal((h.call("start").body as Dto).attempts, 3);
  job = h.call("fail", { error: "exit 3" }).body as Dto;
  assert.equal(job.status, "failed");
  assert.equal(job.attempts, 3);
  assert.equal(job.retryAt, null);
  assert.equal(job.nextRunAt, null);
  assert.equal(h.get().status, "failed");
});

test("a single-attempt job fails straight away", () => {
  const h = harness({ name: "once", command: "x", retry: { maxAttempts: 1 } });
  h.call("start");
  const job = h.call("fail").body as Dto;
  assert.equal(job.status, "failed");
  assert.equal(job.lastError, "job failed");
});

test("backoff doubles up to maxBackoff", () => {
  const h = harness({ name: "capped", command: "x", retry: { maxAttempts: 5, backoff: "1s", maxBackoff: "1500ms" } });
  const delays: number[] = [];
  let elapsed = 0;
  for (let run = 1; run <= 4; run++) {
    assert.equal(h.call("start").status, 200);
    const job = h.call("fail").body as Dto;
    assert.equal(job.status, "queued", `run ${run}`);
    const wait = Date.parse(job.retryAt as string) - (T0 + elapsed);
    delays.push(wait);
    h.clock.advance(wait);
    elapsed += wait;
  }
  assert.deepEqual(delays, [1000, 1500, 1500, 1500]);
  h.call("start");
  assert.equal((h.call("fail").body as Dto).status, "failed");
});

test("a pending retry is the next run", () => {
  const h = harness({ name: "nightly", command: "x", schedule: "daily at 09:30", retry: { maxAttempts: 3, backoff: "30s" } });
  assert.equal(h.get().nextRunAt, "2026-03-02T09:30:00.000Z");
  h.call("start");
  const failed = h.call("fail").body as Dto;
  assert.equal(failed.retryAt, at(30_000));
  assert.equal(failed.nextRunAt, at(30_000));
  assert.equal(h.get().nextRunAt, at(30_000));
  h.clock.advance(30_000);
  const running = h.call("start").body as Dto;
  assert.equal(running.retryAt, null);
  assert.equal(running.nextRunAt, null);

  const plain = harness({ name: "adhoc", command: "x", retry: { maxAttempts: 2, backoff: "5s" } });
  plain.call("start");
  assert.equal((plain.call("fail").body as Dto).nextRunAt, at(5000));
});

test("core helper", () => {
  const policy = { maxAttempts: 3, backoffMs: 1000, maxBackoffMs: 300_000 };
  const t = new Date(T0);
  assert.equal(nextAttemptAt(t, 1, policy)?.toISOString(), at(1000));
  assert.equal(nextAttemptAt(t, 2, policy)?.toISOString(), at(2000));
  assert.equal(nextAttemptAt(t, 3, policy), null);
  assert.equal(nextAttemptAt(t, 1, { ...policy, maxAttempts: 1 }), null);
});
