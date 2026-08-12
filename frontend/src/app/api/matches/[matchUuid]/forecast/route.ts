import { proxyBackend } from "@/lib/backend-proxy";
import { rateLimited } from "@/lib/rate-limited-route";

export const dynamic = "force-dynamic";

export async function GET(
  request: Request,
  { params }: { params: Promise<{ matchUuid: string }> },
) {
  const { matchUuid } = await params;
  return rateLimited(request, () =>
    proxyBackend(`/api/matches/${encodeURIComponent(matchUuid)}/forecast`),
  );
}
