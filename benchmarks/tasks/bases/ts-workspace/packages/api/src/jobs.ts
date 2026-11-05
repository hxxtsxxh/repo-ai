// Job endpoints. Every handler receives the authenticated principal.
import type { Job, JobStatus } from "../../core/src/types.ts";
import { JOB_STATUSES } from "../../core/src/types.ts";
import { canTransition } from "../../core/src/lifecycle.ts";
import type { EventBus } from "../../core/src/events.ts";
import type { ApiRequest, ApiResponse } from "./http.ts";
import { json, queryParam } from "./http.ts";
import { badRequest, conflict, notFound } from "./errors.ts";
import { paginate, parseLimit } from "./pagination.ts";
import { toJobDto } from "./serialize.ts";
import { validateJobInput } from "./validation.ts";
import type { JobStore } from "./store.ts";

export interface JobsContext {
  store: JobStore;
  events: EventBus;
  clock: () => Date;
}

function requireJob(ctx: JobsContext, id: string): Job {
  const job = ctx.store.get(id);
  if (!job) throw notFound(`job ${id} not found`);
  return job;
}

function buildFilter(request: ApiRequest): (job: Job) => boolean {
  const checks: Array<(job: Job) => boolean> = [];

  const statusParam = queryParam(request, "status");
  if (statusParam !== undefined) {
    const wanted = statusParam
      .split(",")
      .map((s) => s.trim().toLowerCase())
      .filter(Boolean);
    const unknown = wanted.filter((s) => !JOB_STATUSES.includes(s as JobStatus));
    if (unknown.length > 0) throw badRequest(`unknown status: ${unknown.join(", ")}`);
    checks.push((job) => wanted.includes(job.status));
  }

  const tag = queryParam(request, "tag");
  if (tag !== undefined) checks.push((job) => job.tags.includes(tag));

  return (job) => checks.every((check) => check(job));
}

export function listJobs(ctx: JobsContext, request: ApiRequest): ApiResponse {
  const jobs = ctx.store.list(buildFilter(request));
  const page = paginate(jobs, parseLimit(queryParam(request, "limit")), queryParam(request, "cursor"));
  const now = ctx.clock();
  return json(200, {
    items: page.items.map((job) => toJobDto(job, now)),
    nextCursor: page.nextCursor,
  });
}

export function getJob(ctx: JobsContext, id: string): ApiResponse {
  return json(200, toJobDto(requireJob(ctx, id), ctx.clock()));
}

export function createJob(ctx: JobsContext, request: ApiRequest): ApiResponse {
  const input = validateJobInput(request.body);
  const duplicate = ctx.store.list((job) => job.name === input.name && job.status === "queued");
  if (duplicate.length > 0) throw conflict(`a queued job named ${input.name} already exists`);
  const job = ctx.store.create(input);
  ctx.events.emit("job:created", job);
  return json(201, toJobDto(job, ctx.clock()), { location: `/jobs/${job.id}` });
}

function transition(ctx: JobsContext, id: string, to: JobStatus, event: string, extra: Partial<Job> = {}) {
  const job = requireJob(ctx, id);
  if (!canTransition(job.status, to)) {
    throw conflict(`job ${id} is ${job.status} and cannot become ${to}`);
  }
  const updated = ctx.store.setStatus(id, to, extra);
  ctx.events.emit(event, updated);
  return json(200, toJobDto(updated, ctx.clock()));
}

export function cancelJob(ctx: JobsContext, id: string): ApiResponse {
  return transition(ctx, id, "cancelled", "job:cancelled");
}

export function retryJob(ctx: JobsContext, id: string): ApiResponse {
  return transition(ctx, id, "queued", "job:retried", { lastError: undefined });
}
