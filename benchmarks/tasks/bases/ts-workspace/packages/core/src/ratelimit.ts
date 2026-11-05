// Token-bucket rate limiter. Tokens refill continuously at `refillPerSecond`.

export type Clock = () => number;

export class TokenBucket {
  capacity: number;
  refillPerSecond: number;
  tokens: number;
  updatedAt: number;
  now: Clock;

  constructor(capacity: number, refillPerSecond: number, now: Clock = () => Date.now()) {
    if (capacity <= 0 || refillPerSecond <= 0) throw new RangeError("capacity and refill must be positive");
    this.capacity = capacity;
    this.refillPerSecond = refillPerSecond;
    this.tokens = capacity;
    this.now = now;
    this.updatedAt = now();
  }

  refill(): void {
    const current = this.now();
    const elapsedMs = Math.max(0, current - this.updatedAt);
    this.tokens = Math.min(this.capacity, this.tokens + (elapsedMs / 1000) * this.refillPerSecond);
    this.updatedAt = current;
  }

  tryTake(count = 1): boolean {
    this.refill();
    if (this.tokens >= count) {
      this.tokens -= count;
      return true;
    }
    return false;
  }

  // Milliseconds until `count` tokens will be available (0 if available now).
  retryAfterMs(count = 1): number {
    this.refill();
    if (this.tokens >= count) return 0;
    return Math.ceil(((count - this.tokens) / this.refillPerSecond) * 1000);
  }
}

export class KeyedRateLimiter {
  buckets: Map<string, TokenBucket>;
  capacity: number;
  refillPerSecond: number;
  now: Clock;

  constructor(capacity: number, refillPerSecond: number, now: Clock = () => Date.now()) {
    this.buckets = new Map();
    this.capacity = capacity;
    this.refillPerSecond = refillPerSecond;
    this.now = now;
  }

  bucket(key: string): TokenBucket {
    let bucket = this.buckets.get(key);
    if (!bucket) {
      bucket = new TokenBucket(this.capacity, this.refillPerSecond, this.now);
      this.buckets.set(key, bucket);
    }
    return bucket;
  }
}
