export type RateLimitDecision = {
  allowed: boolean;
  limit: number;
  remaining: number;
  resetAt: number;
  retryAfterSeconds: number;
};

type ClientWindow = {
  timestamps: number[];
  lastSeenAt: number;
};

export class SlidingWindowRateLimiter {
  private readonly clients = new Map<string, ClientWindow>();
  private readonly limit: number;
  private readonly windowMilliseconds: number;
  private readonly maxClients: number;

  constructor(limit: number, windowMilliseconds: number, maxClients = 10_000) {
    this.limit = limit;
    this.windowMilliseconds = windowMilliseconds;
    this.maxClients = maxClients;
  }

  consume(key: string, now = Date.now()): RateLimitDecision {
    const cutoff = now - this.windowMilliseconds;
    let window = this.clients.get(key);

    if (!window) {
      this.makeRoom(now);
      window = { timestamps: [], lastSeenAt: now };
      this.clients.set(key, window);
    }

    while (window.timestamps.length > 0 && window.timestamps[0] <= cutoff) {
      window.timestamps.shift();
    }

    const allowed = window.timestamps.length < this.limit;
    if (allowed) {
      window.timestamps.push(now);
    }
    window.lastSeenAt = now;

    const resetAt = window.timestamps[0] + this.windowMilliseconds;
    return {
      allowed,
      limit: this.limit,
      remaining: Math.max(0, this.limit - window.timestamps.length),
      resetAt,
      retryAfterSeconds: Math.max(1, Math.ceil((resetAt - now) / 1000)),
    };
  }

  private makeRoom(now: number) {
    if (this.clients.size < this.maxClients) {
      return;
    }

    const cutoff = now - this.windowMilliseconds;
    for (const [key, window] of this.clients) {
      if (window.lastSeenAt <= cutoff) {
        this.clients.delete(key);
      }
    }

    if (this.clients.size >= this.maxClients) {
      const oldest = [...this.clients].reduce((candidate, entry) =>
        entry[1].lastSeenAt < candidate[1].lastSeenAt ? entry : candidate,
      );
      this.clients.delete(oldest[0]);
    }
  }
}

export function positiveInteger(value: string | undefined, fallback: number) {
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : fallback;
}
