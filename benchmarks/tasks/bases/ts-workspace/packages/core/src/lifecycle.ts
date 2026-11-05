// Which status changes are legal for a job.
import type { JobStatus } from "./types.ts";

export const TRANSITIONS: Record<JobStatus, readonly JobStatus[]> = {
  queued: ["running", "cancelled"],
  running: ["succeeded", "failed", "cancelled"],
  succeeded: [],
  failed: ["queued"],
  cancelled: [],
};

export function canTransition(from: JobStatus, to: JobStatus): boolean {
  return (TRANSITIONS[from] ?? []).includes(to);
}

export function isTerminal(status: JobStatus): boolean {
  return (TRANSITIONS[status] ?? []).length === 0;
}

export class TransitionError extends Error {
  from: JobStatus;
  to: JobStatus;

  constructor(from: JobStatus, to: JobStatus) {
    super(`cannot move job from ${from} to ${to}`);
    this.name = "TransitionError";
    this.from = from;
    this.to = to;
  }
}

export function assertTransition(from: JobStatus, to: JobStatus): void {
  if (!canTransition(from, to)) throw new TransitionError(from, to);
}
