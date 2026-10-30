// String helpers for terminal output.

const ELLIPSIS = "…";

// Visible width, counting each code point once (no ANSI escapes expected).
export function displayWidth(text: string): number {
  return Array.from(text).length;
}

// truncate("scheduler", 6) === "sched…"; the result is never wider than `width`.
export function truncate(text: string, width: number): string {
  if (width <= 0) return "";
  const chars = Array.from(text);
  if (chars.length <= width) return text;
  if (width === 1) return ELLIPSIS;
  return chars.slice(0, width - 1).join("") + ELLIPSIS;
}

export function padEndTo(text: string, width: number): string {
  const gap = width - displayWidth(text);
  return gap > 0 ? text + " ".repeat(gap) : text;
}

export function pluralize(count: number, singular: string, plural = `${singular}s`): string {
  return `${count} ${count === 1 ? singular : plural}`;
}

export function slug(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}
