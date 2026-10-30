// Validation for job creation payloads.
import type { JobInput } from "../../core/src/types.ts";
import { parseDuration } from "../../core/src/duration.ts";
import { parseSchedule } from "../../core/src/schedule.ts";
import { badRequest } from "./errors.ts";

export const DEFAULT_TIMEOUT_MS = 60_000;
const NAME_RE = /^[a-z0-9][a-z0-9-]{0,62}$/;

function durationField(body: Record<string, unknown>, field: string, fallback: number): number {
  const raw = body[field];
  if (raw === undefined || raw === null) return fallback;
  try {
    return parseDuration(raw as string | number);
  } catch (error) {
    throw badRequest(`${field}: ${(error as Error).message}`);
  }
}

export function validateJobInput(raw: unknown): JobInput {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) {
    throw badRequest("body must be a JSON object");
  }
  const body = raw as Record<string, unknown>;
  const errors: string[] = [];

  const name = typeof body.name === "string" ? body.name.trim() : "";
  if (!NAME_RE.test(name)) errors.push("name must be 1-63 lowercase letters, digits or dashes");
  const command = typeof body.command === "string" ? body.command.trim() : "";
  if (!command) errors.push("command is required");

  let schedule: string | null = null;
  if (body.schedule !== undefined && body.schedule !== null) {
    try {
      parseSchedule(String(body.schedule));
      schedule = String(body.schedule);
    } catch (error) {
      errors.push(`schedule: ${(error as Error).message}`);
    }
  }

  const tags = Array.isArray(body.tags) ? body.tags.map(String) : [];
  const retryBody = (body.retry ?? {}) as Record<string, unknown>;
  const maxAttempts = retryBody.maxAttempts === undefined ? 3 : Number(retryBody.maxAttempts);
  if (!Number.isInteger(maxAttempts) || maxAttempts < 1 || maxAttempts > 10) {
    errors.push("retry.maxAttempts must be an integer between 1 and 10");
  }
  if (errors.length > 0) throw badRequest("invalid job", errors);

  return {
    name,
    command,
    schedule,
    timeoutMs: durationField(body, "timeout", DEFAULT_TIMEOUT_MS),
    retry: {
      maxAttempts,
      backoffMs: durationField(retryBody, "backoff", 1_000),
      maxBackoffMs: durationField(retryBody, "maxBackoff", 300_000),
    },
    tags,
  };
}
