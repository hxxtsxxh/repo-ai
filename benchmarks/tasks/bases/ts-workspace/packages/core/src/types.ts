// Domain types shared by every package.

export type JobStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled";

export const JOB_STATUSES: readonly JobStatus[] = [
  "queued",
  "running",
  "succeeded",
  "failed",
  "cancelled",
];

export interface RetryPolicy {
  maxAttempts: number;
  backoffMs: number;
  maxBackoffMs: number;
}

export interface Job {
  id: string;
  name: string;
  command: string;
  schedule: string | null;
  status: JobStatus;
  attempts: number;
  timeoutMs: number;
  retry: RetryPolicy;
  tags: string[];
  createdAt: string;
  updatedAt: string;
  lastError?: string;
}

export interface JobInput {
  name: string;
  command: string;
  schedule: string | null;
  timeoutMs: number;
  retry: RetryPolicy;
  tags: string[];
}
