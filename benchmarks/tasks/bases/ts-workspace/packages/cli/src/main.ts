// Entry point for the `jobs` CLI.
import { pathToFileURL } from "node:url";
import { createApi } from "../../api/src/server.ts";
import { parseArgs } from "./args.ts";
import type { ApiLike } from "./client.ts";
import { CliError, createLocalClient } from "./client.ts";
import { COMMANDS } from "./commands.ts";
import type { Io } from "./io.ts";
import { processIo } from "./io.ts";

export interface MainDeps {
  api?: ApiLike;
  apiKey?: string;
  env?: Record<string, string | undefined>;
  now?: () => Date;
}

function printHelp(io: Io): void {
  io.out("usage: jobs <command> [options]");
  io.out("");
  for (const [name, command] of Object.entries(COMMANDS)) {
    io.out(`  ${name.padEnd(8)} ${command.summary}`);
  }
}

export async function main(argv: string[], io: Io = processIo, deps: MainDeps = {}): Promise<number> {
  const args = parseArgs(argv);
  if (!args.command || args.command === "help" || args.flags.help === true) {
    printHelp(io);
    return args.command ? 0 : 2;
  }
  const command = COMMANDS[args.command];
  if (!command) {
    io.err(`unknown command: ${args.command}`);
    return 2;
  }
  const env = deps.env ?? process.env;
  const apiKey = String(args.flags.key ?? deps.apiKey ?? env.RUNNER_API_KEY ?? "dev-admin-key");
  const client = createLocalClient(deps.api ?? createApi(), apiKey);
  const now = deps.now ?? (() => new Date());
  try {
    return command.run({ client, io, now }, args);
  } catch (error) {
    if (error instanceof CliError) {
      io.err(`error: ${error.message}`);
      return error.exitCode;
    }
    throw error;
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main(process.argv.slice(2)).then((code) => {
    process.exitCode = code;
  });
}
