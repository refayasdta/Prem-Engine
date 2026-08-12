const DEFAULT_BACKEND = "http://127.0.0.1:8000";

export async function proxyBackend(path: string) {
  const baseUrl = (process.env.PREM_ENGINE_API_BASE_URL ?? DEFAULT_BACKEND).replace(/\/$/, "");
  try {
    const response = await fetch(`${baseUrl}${path}`, {
      cache: "no-store",
      headers: { accept: "application/json" },
    });
    const headers = new Headers({
      "content-type": response.headers.get("content-type") ?? "application/json",
    });
    for (const name of [
      "cache-control",
      "retry-after",
      "x-ratelimit-limit",
      "x-ratelimit-remaining",
      "x-ratelimit-reset",
    ]) {
      const value = response.headers.get(name);
      if (value !== null) {
        headers.set(name, value);
      }
    }
    return new Response(await response.text(), {
      status: response.status,
      headers,
    });
  } catch {
    return Response.json(
      { detail: "Prem Engine API is unavailable. Start the backend and try again." },
      { status: 503 },
    );
  }
}
