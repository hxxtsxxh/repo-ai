// Subcommands of the `jobs` CLI.
import { parseDuration } from "../../core/src/duration.ts";
import { nextRun, parseSchedule } from "../../core/src/schedule.ts";
import type { JobDto } from "../../api/src/serialize.ts";
import type { ParsedArgs } from "./args.ts";
import { flagInt, flagList, flagString } from "./args.ts";
import type { ApiClient } from "./client.ts";
import { CliError } from "./client.ts";
import { formatTimestamp, relativeTime, statusLabel } from "./format.ts";
import type { Io } from "./io.ts";
import { renderTable } from "./table.ts";

export interface CommandContext {
  client: ApiClient;
  io: Io;
  now: () => Date;
}

export interface Command {
  summary: string;
  usage: string;
  run(ctx: CommandContext, args: ParsedArgs): number;
}

interface JobPage {
  items: JobDto[];
  nextCursor: string | null;
}

function requireId(args: ParsedArgs, usage: string): string {
  const id = args.positionals[0];
  if (!id) throw new CliError(`usage: ${usage}`, 2);
  return id;
}

function durationFlag(args: ParsedArgs, name: string): number | undefined {
  const raw = flagString(args.flags, name);
  if (raw === undefined) return undefined;
  try {
    return parseDuration(raw);
  } catch (error) {
    throw new CliError(`--${name}: ${(error as Error).message}`, 2);
  }
}

const list: Command = {
  summary: "List jobs",
  usage: "jobs list [--status s1,s2] [--tag t] [--limit n] [--all]",
  run(ctx, args) {
    const query: Record<string, string> = {};
    const statuses = flagList(args.flags, "status");
    if (statuses.length > 0) query.status = statuses.join(",");
    const tag = flagString(args.flags, "tag");
    if (tag) query.tag = tag;
    const limit = flagInt(args.flags, "limit");
    if (limit !== undefined) query.limit = String(limit);

    const jobs: JobDto[] = [];
    let page = ctx.client.request<JobPage>("GET", "/jobs", { query });
    jobs.push(...page.items);
    while (args.flags.all === true && page.nextCursor) {
      page = ctx.client.request<JobPage>("GET", "/jobs", { query: { ...query, cursor: page.nextCursor } });
      jobs.push(...page.items);
    }
    if (jobs.length === 0) {
      ctx.io.out("No jobs found.");
      return 0;
    }
    const now = ctx.now();
    const lines = renderTable<JobDto>(
      [
        { header: "ID", value: (j) => j.id },
        { header: "NAME", value: (j) => j.name, maxWidth: 24 },
        { header: "STATUS", value: (j) => statusLabel(j.status) },
        { header: "SCHEDULE", value: (j) => j.schedule ?? "-", maxWidth: 22 },
        { header: "NEXT RUN", value: (j) => (j.nextRunAt ? relativeTime(new Date(j.nextRunAt), now) : "-") },
        { header: "TIMEOUT", value: (j) => j.timeout },
      ],
      jobs,
    );
    lines.forEach((line) => ctx.io.out(line));
    return 0;
  },
};

const show: Command = {
  summary: "Show one job",
  usage: "jobs show <id>",
  run(ctx, args) {
    const job = ctx.client.request<JobDto>("GET", `/jobs/${encodeURIComponent(requireId(args, this.usage))}`);
    const rows: Array<[string, string]> = [
      ["id", job.id],
      ["name", job.name],
      ["status", statusLabel(job.status)],
      ["command", job.command],
      ["schedule", job.scheduleDescription ?? "-"],
      ["next run", formatTimestamp(job.nextRunAt)],
      ["timeout", job.timeout],
      ["retries", `${job.retry.maxAttempts} (backoff ${job.retry.backoff}, max ${job.retry.maxBackoff})`],
      ["tags", job.tags.length > 0 ? job.tags.join(", ") : "-"],
    ];
    const width = Math.max(...rows.map(([k]) => k.length));
    for (const [key, value] of rows) ctx.io.out(`${key.padEnd(width)}  ${value}`);
    return 0;
  },
};

const create: Command = {
  summary: "Create a job",
  usage: "jobs create <name> --command <cmd> [--schedule <spec>] [--timeout <dur>] [--retries n] [--backoff <dur>] [--tag a,b]",
  run(ctx, args) {
    const name = requireId(args, this.usage);
    const command = flagString(args.flags, "command");
    if (!command) throw new CliError("--command is required", 2);
    const body: Record<string, unknown> = { name, command, tags: flagList(args.flags, "tag") };
    const schedule = flagString(args.flags, "schedule");
    if (schedule) body.schedule = schedule;
    const timeout = durationFlag(args, "timeout");
    if (timeout !== undefined) body.timeout = timeout;
    const retry: Record<string, unknown> = {};
    const retries = flagInt(args.flags, "retries");
    if (retries !== undefined) retry.maxAttempts = retries;
    const backoff = durationFlag(args, "backoff");
    if (backoff !== undefined) retry.backoff = backoff;
    if (Object.keys(retry).length > 0) body.retry = retry;

    const job = ctx.client.request<JobDto>("POST", "/jobs", { body });
    ctx.io.out(`Created ${job.id} (${job.name})`);
    return 0;
  },
};

function transitionCommand(verb: string, past: string): Command {
  return {
    summary: `${verb[0].toUpperCase()}${verb.slice(1)} a job`,
    usage: `jobs ${verb} <id>`,
    run(ctx, args) {
      const id = requireId(args, this.usage);
      const job = ctx.client.request<JobDto>("POST", `/jobs/${encodeURIComponent(id)}/${verb}`);
      ctx.io.out(`${past} ${job.id} (now ${statusLabel(job.status)})`);
      return 0;
    },
  };
}

const next: Command = {
  summary: "Preview upcoming run times for a schedule",
  usage: 'jobs next "<schedule>" [--count n] [--from <iso>]',
  run(ctx, args) {
    const spec = args.positionals.join(" ");
    if (!spec) throw new CliError(`usage: ${this.usage}`, 2);
    let schedule;
    try {
      schedule = parseSchedule(spec);
    } catch (error) {
      throw new CliError((error as Error).message, 2);
    }
    const count = flagInt(args.flags, "count") ?? 3;
    const fromFlag = flagString(args.flags, "from");
    let cursor = fromFlag ? new Date(fromFlag) : ctx.now();
    for (let i = 0; i < count; i++) {
      cursor = nextRun(schedule, cursor);
      ctx.io.out(cursor.toISOString());
    }
    return 0;
  },
};

export const COMMANDS: Record<string, Command> = {
  list,
  show,
  create,
  cancel: transitionCommand("cancel", "Cancelled"),
  retry: transitionCommand("retry", "Requeued"),
  next,
};
