import { test } from "node:test";
import assert from "node:assert/strict";
import { DependencyError, executionOrder } from "../src/plan.ts";
import type { PlannedJob } from "../src/plan.ts";

const j = (id: string, ...dependsOn: string[]): PlannedJob => ({ id, dependsOn });

// Straightforward reference implementation of the documented order.
function reference(jobs: PlannedJob[]): string[] {
  const done = new Set<string>();
  const remaining = [...jobs];
  const order: string[] = [];
  while (remaining.length > 0) {
    const index = remaining.findIndex((job) => job.dependsOn.every((dep) => done.has(dep)));
    const [job] = remaining.splice(index, 1);
    done.add(job.id);
    order.push(job.id);
  }
  return order;
}

function counted(jobs: PlannedJob[]) {
  let reads = 0;
  const wrapped = jobs.map(({ id, dependsOn }) => {
    const job = { id } as PlannedJob;
    Object.defineProperty(job, "dependsOn", {
      enumerable: true,
      get() {
        reads += 1;
        return dependsOn;
      },
    });
    return job;
  });
  return { wrapped, reads: () => reads };
}

test("stable order: first listed ready job wins", () => {
  assert.deepEqual(executionOrder([j("c", "b"), j("b"), j("a")]), ["b", "c", "a"]);
  assert.deepEqual(
    executionOrder([j("deploy", "build", "test"), j("test", "build"), j("build"), j("lint")]),
    ["build", "test", "deploy", "lint"],
  );
  assert.deepEqual(executionOrder([j("x", "y", "y"), j("y")]), ["y", "x"]);
  assert.deepEqual(executionOrder([]), []);
});

test("same order as the reference on random graphs", () => {
  let seed = 12345;
  const rand = () => {
    seed = (seed * 1103515245 + 12345) % 2147483648;
    return seed / 2147483648;
  };
  for (let round = 0; round < 30; round++) {
    const n = 5 + Math.floor(rand() * 120);
    const ranks = Array.from({ length: n }, (_, i) => i).sort(() => rand() - 0.5);
    const jobs: PlannedJob[] = [];
    for (let i = 0; i < n; i++) {
      const deps: string[] = [];
      for (let k = 0; k < n; k++) {
        if (ranks[k] < ranks[i] && rand() < 0.08) deps.push(`n${k}`);
      }
      jobs.push(j(`n${i}`, ...deps));
    }
    assert.deepEqual(executionOrder(jobs), reference(jobs), `round ${round}`);
  }
});

test("errors are unchanged", () => {
  const check = (jobs: PlannedJob[], pattern: RegExp, ids: string[]) =>
    assert.throws(() => executionOrder(jobs), (error: unknown) => {
      assert.ok(error instanceof DependencyError);
      assert.match(error.message, pattern);
      assert.deepEqual(error.ids, ids);
      return true;
    });
  check([j("a", "ghost")], /unknown job\(s\) ghost/, ["a"]);
  check([j("a"), j("b"), j("a")], /duplicate job id a/, ["a"]);
  check([j("a"), j("b", "c"), j("c", "b"), j("d", "c"), j("e")], /cycle/, ["b", "c", "d"]);
  check([j("self", "self")], /cycle/, ["self"]);
});

test("long chains are planned without rescanning every job", () => {
  const n = 3000;
  const raw = Array.from({ length: n }, (_, i) => j(`job-${i}`, ...(i + 1 < n ? [`job-${i + 1}`] : [])));
  const { wrapped, reads } = counted(raw);
  const order = executionOrder(wrapped);
  assert.equal(order.length, n);
  assert.equal(order[0], `job-${n - 1}`);
  assert.equal(order[n - 1], "job-0");
  assert.ok(reads() <= 4 * n, `dependsOn was read ${reads()} times for ${n} jobs`);
});

test("wide fan-in stays cheap", () => {
  const n = 3000;
  const raw = [...Array.from({ length: n - 1 }, (_, i) => j(`leaf-${i}`, "root")), j("root")];
  const { wrapped, reads } = counted(raw);
  const order = executionOrder(wrapped);
  assert.equal(order[0], "root");
  assert.equal(order[1], "leaf-0");
  assert.ok(reads() <= 4 * n, `dependsOn was read ${reads()} times for ${n} jobs`);
});
