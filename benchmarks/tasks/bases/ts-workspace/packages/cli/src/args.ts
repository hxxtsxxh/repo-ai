// Minimal argv parser: `cmd pos1 --flag value --flag=value --no-flag -v`.

export type FlagValue = string | boolean;

export interface ParsedArgs {
  command: string | null;
  positionals: string[];
  flags: Record<string, FlagValue>;
}

const SHORT_FLAGS: Record<string, string> = { h: "help", v: "verbose", a: "all", q: "quiet" };

export function parseArgs(argv: string[]): ParsedArgs {
  const positionals: string[] = [];
  const flags: Record<string, FlagValue> = {};
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === "--") {
      positionals.push(...argv.slice(i + 1));
      break;
    }
    if (arg.startsWith("--")) {
      const body = arg.slice(2);
      const eq = body.indexOf("=");
      if (eq >= 0) {
        flags[body.slice(0, eq)] = body.slice(eq + 1);
        continue;
      }
      if (body.startsWith("no-")) {
        flags[body.slice(3)] = false;
        continue;
      }
      const next = argv[i + 1];
      if (next !== undefined && !next.startsWith("-")) {
        flags[body] = next;
        i++;
      } else {
        flags[body] = true;
      }
      continue;
    }
    if (arg.startsWith("-") && arg.length > 1) {
      for (const ch of arg.slice(1)) flags[SHORT_FLAGS[ch] ?? ch] = true;
      continue;
    }
    positionals.push(arg);
  }
  return { command: positionals.shift() ?? null, positionals, flags };
}

export function flagString(flags: Record<string, FlagValue>, name: string): string | undefined {
  const value = flags[name];
  return typeof value === "string" ? value : undefined;
}

export function flagList(flags: Record<string, FlagValue>, name: string): string[] {
  const value = flagString(flags, name);
  return value ? value.split(",").map((s) => s.trim()).filter(Boolean) : [];
}

export function flagInt(flags: Record<string, FlagValue>, name: string): number | undefined {
  const value = flagString(flags, name);
  if (value === undefined) return undefined;
  const n = Number(value);
  if (!Number.isInteger(n)) throw new TypeError(`--${name} must be an integer`);
  return n;
}
