// In-memory job storage. Listing order is creation time, then id.
import type { Job, JobInput, JobStatus } from "../../core/src/types.ts";

export type Clock = () => Date;

export class JobStore {
  jobs: Map<string, Job>;
  counter: number;
  clock: Clock;

  constructor(clock: Clock = () => new Date()) {
    this.jobs = new Map();
    this.counter = 0;
    this.clock = clock;
  }

  nextId(): string {
    this.counter += 1;
    return `job_${String(this.counter).padStart(4, "0")}`;
  }

  create(input: JobInput): Job {
    const now = this.clock().toISOString();
    const job: Job = {
      id: this.nextId(),
      ...input,
      status: "queued",
      attempts: 0,
      createdAt: now,
      updatedAt: now,
    };
    this.jobs.set(job.id, job);
    return job;
  }

  get(id: string): Job | undefined {
    return this.jobs.get(id);
  }

  update(id: string, patch: Partial<Job>): Job {
    const job = this.jobs.get(id);
    if (!job) throw new Error(`job ${id} does not exist`);
    const updated: Job = { ...job, ...patch, id, updatedAt: this.clock().toISOString() };
    this.jobs.set(id, updated);
    return updated;
  }

  setStatus(id: string, status: JobStatus, extra: Partial<Job> = {}): Job {
    return this.update(id, { ...extra, status });
  }

  list(filter?: (job: Job) => boolean): Job[] {
    const all = [...this.jobs.values()].filter((job) => (filter ? filter(job) : true));
    return all.sort((a, b) =>
      a.createdAt === b.createdAt ? a.id.localeCompare(b.id) : a.createdAt.localeCompare(b.createdAt),
    );
  }

  delete(id: string): boolean {
    return this.jobs.delete(id);
  }
}
