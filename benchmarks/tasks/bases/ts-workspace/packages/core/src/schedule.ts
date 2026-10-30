// Schedules: "every 15m", "daily at 09:30", "weekly on mon at 08:00". All times are UTC.
import { parseDuration } from "./duration.ts";

export type Schedule =
  | { kind: "interval"; everyMs: number }
  | { kind: "daily"; hour: number; minute: number }
  | { kind: "weekly"; weekday: number; hour: number; minute: number };

const DAY_MS = 86_400_000;
const WEEKDAYS = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"];

function parseClock(text: string): { hour: number; minute: number } {
  const match = /^(\d{1,2}):(\d{2})$/.exec(text);
  if (!match) throw new SyntaxError(`invalid time of day: "${text}"`);
  const hour = Number(match[1]);
  const minute = Number(match[2]);
  if (hour > 23 || minute > 59) throw new RangeError(`invalid time of day: "${text}"`);
  return { hour, minute };
}

export function parseSchedule(spec: string): Schedule {
  const text = spec.trim().toLowerCase().replace(/\s+/g, " ");
  let match = /^every (.+)$/.exec(text);
  if (match) {
    const everyMs = parseDuration(match[1]);
    if (everyMs < 1_000) throw new RangeError("interval must be at least 1s");
    return { kind: "interval", everyMs };
  }
  match = /^daily(?: at)? (\d{1,2}:\d{2})$/.exec(text);
  if (match) return { kind: "daily", ...parseClock(match[1]) };
  match = /^weekly on ([a-z]{3})(?: at)? (\d{1,2}:\d{2})$/.exec(text);
  if (match) {
    const weekday = WEEKDAYS.indexOf(match[1]);
    if (weekday < 0) throw new SyntaxError(`unknown weekday: "${match[1]}"`);
    return { kind: "weekly", weekday, ...parseClock(match[2]) };
  }
  throw new SyntaxError(`unrecognised schedule: "${spec}"`);
}

// The first run strictly after `from`.
export function nextRun(schedule: Schedule, from: Date): Date {
  const fromMs = from.getTime();
  if (schedule.kind === "interval") return new Date(fromMs + schedule.everyMs);

  const midnight = Date.UTC(from.getUTCFullYear(), from.getUTCMonth(), from.getUTCDate());
  const timeOfDay = (schedule.hour * 60 + schedule.minute) * 60_000;
  if (schedule.kind === "daily") {
    let candidate = midnight + timeOfDay;
    if (candidate <= fromMs) candidate += DAY_MS;
    return new Date(candidate);
  }
  const daysAhead = (schedule.weekday - from.getUTCDay() + 7) % 7;
  let target = midnight + daysAhead * DAY_MS + timeOfDay;
  if (target <= fromMs) target += 7 * DAY_MS;
  return new Date(target);
}

export function describeSchedule(schedule: Schedule): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  if (schedule.kind === "interval") return `every ${schedule.everyMs / 1000}s`;
  const clock = `${pad(schedule.hour)}:${pad(schedule.minute)} UTC`;
  if (schedule.kind === "daily") return `daily at ${clock}`;
  return `weekly on ${WEEKDAYS[schedule.weekday]} at ${clock}`;
}
