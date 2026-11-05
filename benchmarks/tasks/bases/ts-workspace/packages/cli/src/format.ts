// Presentation helpers for the CLI.
import { formatDuration } from "../../core/src/duration.ts";

export function statusLabel(status: string): string {
  return status.toUpperCase();
}

// "in 5m", "2h ago", "now"
export function relativeTime(target: Date, now: Date): string {
  const diff = target.getTime() - now.getTime();
  if (Math.abs(diff) < 1_000) return "now";
  const text = formatDuration(Math.abs(diff)).split(" ")[0];
  return diff > 0 ? `in ${text}` : `${text} ago`;
}

export function formatTimestamp(iso: string | null): string {
  if (!iso) return "-";
  const date = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())} ${pad(
    date.getUTCHours(),
  )}:${pad(date.getUTCMinutes())} UTC`;
}
