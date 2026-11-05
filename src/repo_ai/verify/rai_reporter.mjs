// repo-ai test-outcome reporter for `node --test` (no dependencies).
//
// Copied into the disposable workspace and loaded inside the sandbox with
// `--test-reporter=<this file> --test-reporter-destination=<OUT.jsonl>`,
// beside the default `spec` reporter on stdout. One JSON line per event:
//
//   {"e": "start", "id": ..., "path": ..., "n": nesting}
//   {"e": "end", "id": ..., "path": ..., "n": nesting, "o": "pass|fail|skip", "msg": ..., "dur": ms, "file": true?}
//   {"e": "file_done", "path": ...}   (the file's child process finished)
//   {"e": "done"}
//
// `id` joins the names of enclosing tests with " > ". A test file's own entry
// (the runner's per-file wrapper, named by its path) is marked "file": true.
// Only names, outcomes, the first line of each failure and durations are
// written: no values, environment or full output.

const MAX = 300;

function message(details) {
  const err = details && details.error;
  if (!err) return "";
  const inner = err.cause && typeof err.cause === "object" ? err.cause : err;
  const text = String((inner && (inner.message || inner.code)) || err.message || "");
  const name = inner && inner.name && inner.name !== "Error" ? inner.name + ": " : "";
  return (name + (text.split("\n")[0] || "")).slice(0, MAX);
}

export default async function* raiReporter(source) {
  const stacks = new Map(); // file -> names by nesting level
  for await (const ev of source) {
    const d = ev.data || {};
    if (ev.type === "test:complete") {
      // a test file's own entry completes when its child process is done: the file finished
      const n0 = Number.isInteger(d.nesting) ? d.nesting : 0;
      if (n0 === 0 && typeof d.name === "string" && d.file && d.file.endsWith(d.name.replace(/^\.\//, ""))) {
        yield JSON.stringify({ e: "file_done", path: d.file }) + "\n";
      }
      continue;
    }
    if (!["test:start", "test:pass", "test:fail"].includes(ev.type)) continue;
    const file = d.file || "";
    let stack = stacks.get(file);
    if (!stack) {
      stack = [];
      stacks.set(file, stack);
    }
    const n = Number.isInteger(d.nesting) ? d.nesting : 0;
    if (ev.type === "test:start") {
      stack.length = n;
      stack[n] = String(d.name);
      yield JSON.stringify({ e: "start", id: stack.slice(0, n + 1).join(" > "), path: file, n }) + "\n";
      continue;
    }
    const names = stack.slice(0, n);
    names.push(String(d.name));
    const details = d.details || {};
    const isFile = n === 0 && (details.type === undefined || details.type === "test") &&
      typeof d.name === "string" && file !== "" && file.endsWith(d.name.replace(/^\.\//, ""));
    const out = {
      e: "end", id: names.join(" > "), path: file, n,
      // a todo test may fail without failing the run (node exits 0): like a skip, it verifies nothing
      o: d.skip || d.todo ? "skip" : (ev.type === "test:fail" ? "fail" : "pass"),
      msg: ev.type === "test:fail" && !d.todo ? message(details) : "",
      dur: typeof details.duration_ms === "number" ? Math.round(details.duration_ms) : null,
    };
    if (isFile) out.file = true;
    if (details.type === "suite") out.suite = true;
    yield JSON.stringify(out) + "\n";
  }
  yield JSON.stringify({ e: "done" }) + "\n";
}
