const DEFAULT_BACKEND = "http://127.0.0.1:8000";

export async function proxyBackend(path: string) {
  const baseUrl = (process.env.PREM_ENGINE_API_BASE_URL ?? DEFAULT_BACKEND).replace(/\/$/, "");
  try {
    const response = await fetch(`${baseUrl}${path}`, {
      cache: "no-store",
      headers: { accept: "application/json" },
    });
    return new Response(await response.text(), {
      status: response.status,
      headers: { "content-type": response.headers.get("content-type") ?? "application/json" },
    });
  } catch {
    return Response.json(
      { detail: "Prem Engine API is unavailable. Start the backend and try again." },
      { status: 503 },
    );
  }
}
