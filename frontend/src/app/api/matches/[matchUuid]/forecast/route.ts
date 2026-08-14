import { proxyBackend } from "@/lib/backend-proxy";
import { rateLimited } from "@/lib/rate-limited-route";

export const dynamic = "force-dynamic";

export async function GET(
  request: Request,
  { params }: { params: Promise<{ matchUuid: string }> },
) {
  const { matchUuid } = await params;
  const deviceUuid = new URL(request.url).searchParams.get("device_uuid");
  if (!deviceUuid) {
    return Response.json(
      { detail: "A local device identity is required." },
      { status: 400 },
    );
  }
  return rateLimited(request, () =>
    proxyBackend(
      `/api/matches/${encodeURIComponent(matchUuid)}/forecast?device_uuid=${encodeURIComponent(deviceUuid)}`,
    ),
  );
}

export async function POST(
  request: Request,
  { params }: { params: Promise<{ matchUuid: string }> },
) {
  const { matchUuid } = await params;
  const body = await request.text();
  return rateLimited(request, () =>
    proxyBackend(`/api/matches/${encodeURIComponent(matchUuid)}/play`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body,
    }),
  );
}
