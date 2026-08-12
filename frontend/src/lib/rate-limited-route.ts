import { SlidingWindowRateLimiter, positiveInteger, type RateLimitDecision } from "./rate-limit";

const enabled = process.env.PREM_ENGINE_RATE_LIMIT_ENABLED !== "false";
const requestLimit = positiveInteger(process.env.PREM_ENGINE_RATE_LIMIT_REQUESTS, 60);
const windowSeconds = positiveInteger(process.env.PREM_ENGINE_RATE_LIMIT_WINDOW_SECONDS, 60);
const limiter = new SlidingWindowRateLimiter(requestLimit, windowSeconds * 1000);

export async function rateLimited(
  request: Request,
  handler: () => Promise<Response>,
): Promise<Response> {
  if (!enabled) {
    return handler();
  }

  const decision = limiter.consume(clientIdentifier(request));
  if (!decision.allowed) {
    return Response.json(
      { detail: "Rate limit exceeded. Try again later." },
      {
        status: 429,
        headers: {
          ...rateLimitHeaders(decision),
          "Cache-Control": "no-store",
          "Retry-After": String(decision.retryAfterSeconds),
        },
      },
    );
  }

  const response = await handler();
  if (response.status !== 429) {
    for (const [name, value] of Object.entries(rateLimitHeaders(decision))) {
      response.headers.set(name, value);
    }
  }
  return response;
}

function clientIdentifier(request: Request) {
  const forwarded =
    request.headers.get("x-vercel-forwarded-for") ??
    request.headers.get("x-forwarded-for") ??
    request.headers.get("x-real-ip");
  return forwarded?.split(",", 1)[0].trim() || "unknown";
}

function rateLimitHeaders(decision: RateLimitDecision) {
  return {
    "X-RateLimit-Limit": String(decision.limit),
    "X-RateLimit-Remaining": String(decision.remaining),
    "X-RateLimit-Reset": String(Math.ceil(decision.resetAt / 1000)),
  };
}
