// Job -> response DTO.
import type { Job } from "../../core/src/types.ts";
import { formatDuration } from "../../core/src/duration.ts";
import { describeSchedule, nextRun, parseSchedule } from "../../core/src/schedule.ts";

export interface JobDto {
  id: string;
  name: string;
  command: string;
  status: string;
  attempts: number;
  schedule: string | null;
  scheduleDescription: string | null;
  nextRunAt: string | null;
  timeout: string;
  timeoutMs: number;
  retry: { maxAttempts: number; backoff: string; maxBackoff: string };
  tags: string[];
  createdAt: string;
  updatedAt: string;
  lastError: string | null;
  links: { self: string };
}

export function toJobDto(job: Job, now: Date = new Date()): JobDto {
  const parsed = job.schedule ? parseSchedule(job.schedule) : null;
  const active = job.status === "queued";
  return {
    id: job.id,
    name: job.name,
    command: job.command,
    status: job.status,
    attempts: job.attempts,
    schedule: job.schedule,
    scheduleDescription: parsed ? describeSchedule(parsed) : null,
    nextRunAt: parsed && active ? nextRun(parsed, now).toISOString() : null,
    timeout: formatDuration(job.timeoutMs),
    timeoutMs: job.timeoutMs,
    retry: {
      maxAttempts: job.retry.maxAttempts,
      backoff: formatDuration(job.retry.backoffMs),
      maxBackoff: formatDuration(job.retry.maxBackoffMs),
    },
    tags: [...job.tags],
    createdAt: job.createdAt,
    updatedAt: job.updatedAt,
    lastError: job.lastError ?? null,
    links: { self: `/jobs/${job.id}` },
  };
}
