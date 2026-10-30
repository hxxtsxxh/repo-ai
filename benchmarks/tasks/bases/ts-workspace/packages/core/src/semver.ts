// Minimal semantic-version parsing and range matching (^, ~, comparators, ||).

export interface SemVer {
  major: number;
  minor: number;
  patch: number;
  prerelease: string[];
}

const VERSION_RE = /^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?$/;

export function parseVersion(text: string): SemVer {
  const match = VERSION_RE.exec(text.trim());
  if (!match) throw new SyntaxError(`invalid version: "${text}"`);
  return {
    major: Number(match[1]),
    minor: Number(match[2]),
    patch: Number(match[3]),
    prerelease: match[4] ? match[4].split(".") : [],
  };
}

function compareIdentifiers(a: string, b: string): number {
  const an = /^\d+$/.test(a);
  const bn = /^\d+$/.test(b);
  if (an && bn) return Math.sign(Number(a) - Number(b));
  if (an) return -1;
  if (bn) return 1;
  return a < b ? -1 : a > b ? 1 : 0;
}

export function compareVersions(left: string | SemVer, right: string | SemVer): number {
  const a = typeof left === "string" ? parseVersion(left) : left;
  const b = typeof right === "string" ? parseVersion(right) : right;
  for (const key of ["major", "minor", "patch"] as const) {
    if (a[key] !== b[key]) return Math.sign(a[key] - b[key]);
  }
  if (a.prerelease.length === 0 || b.prerelease.length === 0) {
    return Math.sign(b.prerelease.length - a.prerelease.length);
  }
  const len = Math.max(a.prerelease.length, b.prerelease.length);
  for (let i = 0; i < len; i++) {
    if (a.prerelease[i] === undefined) return -1;
    if (b.prerelease[i] === undefined) return 1;
    const cmp = compareIdentifiers(a.prerelease[i], b.prerelease[i]);
    if (cmp !== 0) return cmp;
  }
  return 0;
}

type Comparator = { op: ">=" | "<=" | ">" | "<" | "="; version: SemVer };

function bump(v: SemVer, part: "major" | "minor" | "patch"): SemVer {
  if (part === "major") return { major: v.major + 1, minor: 0, patch: 0, prerelease: [] };
  if (part === "minor") return { major: v.major, minor: v.minor + 1, patch: 0, prerelease: [] };
  return { major: v.major, minor: v.minor, patch: v.patch + 1, prerelease: [] };
}

function caretUpperBound(v: SemVer): SemVer {
  if (v.major > 0) return bump(v, "major");
  if (v.minor > 0) return bump(v, "minor");
  return bump(v, "patch");
}

function expand(token: string): Comparator[] {
  if (token === "*" || token === "x") return [];
  if (token.startsWith("^")) {
    const v = parseVersion(token.slice(1));
    return [
      { op: ">=", version: v },
      { op: "<", version: caretUpperBound(v) },
    ];
  }
  if (token.startsWith("~")) {
    const v = parseVersion(token.slice(1));
    return [
      { op: ">=", version: v },
      { op: "<", version: bump(v, "minor") },
    ];
  }
  const match = /^(>=|<=|>|<|=)?(.+)$/.exec(token);
  if (!match) throw new SyntaxError(`invalid range token: "${token}"`);
  return [{ op: (match[1] ?? "=") as Comparator["op"], version: parseVersion(match[2]) }];
}

function test(c: Comparator, v: SemVer): boolean {
  const cmp = compareVersions(v, c.version);
  switch (c.op) {
    case ">=":
      return cmp >= 0;
    case "<=":
      return cmp <= 0;
    case ">":
      return cmp > 0;
    case "<":
      return cmp < 0;
    default:
      return cmp === 0;
  }
}

// satisfies("1.4.2", "^1.2.0 || ~0.9.0") === true
export function satisfies(version: string, range: string): boolean {
  const v = parseVersion(version);
  return range.split("||").some((alternative) => {
    const tokens = alternative.trim().split(/\s+/).filter(Boolean);
    return tokens.flatMap(expand).every((c) => test(c, v));
  });
}
