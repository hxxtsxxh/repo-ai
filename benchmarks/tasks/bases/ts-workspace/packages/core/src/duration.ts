// Human-friendly durations: "250ms", "90s", "1h30m", "2d". Bare numbers are seconds.

const UNIT_MS: Record<string, number> = {
  ms: 1,
  s: 1_000,
  m: 60_000,
  h: 3_600_000,
  d: 86_400_000,
};

export function parseDuration(input: string | number): number {
  if (typeof input === "number") {
    if (!Number.isFinite(input) || input < 0) throw new RangeError(`invalid duration: ${input}`);
    return input;
  }
  const text = String(input).trim().toLowerCase().replace(/\s+/g, "");
  if (text === "") throw new SyntaxError("empty duration");
  if (/^\d+$/.test(text)) return Number(text) * 1_000;

  const token = /(\d+(?:\.\d+)?)(ms|s|m|h|d)/y;
  let total = 0;
  let pos = 0;
  while (pos < text.length) {
    token.lastIndex = pos;
    const match = token.exec(text);
    if (!match) throw new SyntaxError(`invalid duration: "${input}"`);
    total += Number(match[1]) * UNIT_MS[match[2]];
    pos = token.lastIndex;
  }
  return Math.round(total);
}

const FORMAT_UNITS: Array<[string, number]> = [
  ["d", 86_400],
  ["h", 3_600],
  ["m", 60],
  ["s", 1],
];

// formatDuration(5_400_000) === "1h 30m". At most two units are shown.
export function formatDuration(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) throw new RangeError(`invalid duration: ${ms}`);
  if (ms < 1_000) return `${Math.round(ms)}ms`;
  let rest = Math.floor(ms / 1_000);
  const parts: string[] = [];
  for (const [label, size] of FORMAT_UNITS) {
    const n = Math.floor(rest / size);
    if (n > 0) {
      parts.push(`${n}${label}`);
      rest -= n * size;
    }
  }
  return parts.slice(0, 2).join(" ");
}
