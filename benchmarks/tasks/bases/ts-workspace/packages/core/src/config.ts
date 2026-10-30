// Runner configuration.
// Precedence (lowest to highest): defaults < config file < environment < overrides.
import { parseDuration } from "./duration.ts";

export type LogLevel = "debug" | "info" | "warn" | "error";

export interface RunnerConfig {
  concurrency: number;
  defaultTimeoutMs: number;
  maxAttempts: number;
  apiPort: number;
  logLevel: LogLevel;
}

export const DEFAULT_CONFIG: RunnerConfig = {
  concurrency: 4,
  defaultTimeoutMs: 60_000,
  maxAttempts: 3,
  apiPort: 8787,
  logLevel: "info",
};

const LOG_LEVELS: readonly LogLevel[] = ["debug", "info", "warn", "error"];

export type Env = Record<string, string | undefined>;

function intFrom(name: string, raw: string): number {
  const value = Number(raw);
  if (!Number.isInteger(value)) throw new TypeError(`${name} must be an integer, got "${raw}"`);
  return value;
}

export function fromEnv(env: Env): Partial<RunnerConfig> {
  const out: Partial<RunnerConfig> = {};
  if (env.RUNNER_CONCURRENCY) out.concurrency = intFrom("RUNNER_CONCURRENCY", env.RUNNER_CONCURRENCY);
  if (env.RUNNER_TIMEOUT) out.defaultTimeoutMs = parseDuration(env.RUNNER_TIMEOUT);
  if (env.RUNNER_MAX_ATTEMPTS) out.maxAttempts = intFrom("RUNNER_MAX_ATTEMPTS", env.RUNNER_MAX_ATTEMPTS);
  if (env.RUNNER_API_PORT) out.apiPort = intFrom("RUNNER_API_PORT", env.RUNNER_API_PORT);
  if (env.RUNNER_LOG_LEVEL) out.logLevel = env.RUNNER_LOG_LEVEL.toLowerCase() as LogLevel;
  return out;
}

export function validateConfig(config: RunnerConfig): RunnerConfig {
  if (config.concurrency < 1 || config.concurrency > 64) {
    throw new RangeError("concurrency must be between 1 and 64");
  }
  if (config.maxAttempts < 1) throw new RangeError("maxAttempts must be at least 1");
  if (config.apiPort < 1 || config.apiPort > 65_535) throw new RangeError("apiPort out of range");
  if (!LOG_LEVELS.includes(config.logLevel)) {
    throw new RangeError(`logLevel must be one of ${LOG_LEVELS.join(", ")}`);
  }
  return config;
}

export interface ResolveOptions {
  file?: Partial<RunnerConfig>;
  env?: Env;
  overrides?: Partial<RunnerConfig>;
}

function defined<T extends object>(partial: T | undefined): Partial<T> {
  const out: Partial<T> = {};
  for (const [key, value] of Object.entries(partial ?? {})) {
    if (value !== undefined) (out as Record<string, unknown>)[key] = value;
  }
  return out;
}

export function resolveConfig(options: ResolveOptions = {}): RunnerConfig {
  return validateConfig({
    ...DEFAULT_CONFIG,
    ...defined(options.file),
    ...fromEnv(options.env ?? {}),
    ...defined(options.overrides),
  });
}
