// Exponential backoff with optional jitter, and a small async retry helper.

export interface BackoffOptions {
  baseMs: number;
  factor: number;
  maxMs: number;
  jitter: number; // 0..1, fraction of the delay that may be shaved off at random
  random?: () => number;
}

export const DEFAULT_BACKOFF: BackoffOptions = {
  baseMs: 500,
  factor: 2,
  maxMs: 30_000,
  jitter: 0,
};

// Delay before retry number `attempt` (1-based).
export function backoffDelay(attempt: number, options: Partial<BackoffOptions> = {}): number {
  const opts = { ...DEFAULT_BACKOFF, ...options };
  if (!Number.isInteger(attempt) || attempt < 1) throw new RangeError("attempt starts at 1");
  const exponential = opts.baseMs * Math.pow(opts.factor, attempt - 1);
  const capped = Math.min(exponential, opts.maxMs);
  const random = opts.random ?? Math.random;
  const jitter = Math.min(Math.max(opts.jitter, 0), 1);
  return Math.round(capped - capped * jitter * random());
}

export interface RetryOptions {
  maxAttempts: number;
  backoff?: Partial<BackoffOptions>;
  sleep?: (ms: number) => Promise<void>;
  shouldRetry?: (error: unknown, attempt: number) => boolean;
  onRetry?: (error: unknown, attempt: number, delayMs: number) => void;
}

const realSleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

export async function retry<T>(fn: (attempt: number) => Promise<T>, options: RetryOptions): Promise<T> {
  const sleep = options.sleep ?? realSleep;
  let attempt = 1;
  for (;;) {
    try {
      return await fn(attempt);
    } catch (error) {
      const allowed = options.shouldRetry ? options.shouldRetry(error, attempt) : true;
      if (!allowed || attempt >= options.maxAttempts) throw error;
      const delay = backoffDelay(attempt, options.backoff);
      options.onRetry?.(error, attempt, delay);
      await sleep(delay);
      attempt += 1;
    }
  }
}
