import { proxyBackend } from "@/lib/backend-proxy";

export const dynamic = "force-dynamic";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ matchUuid: string }> },
) {
  const { matchUuid } = await params;
  return proxyBackend(`/api/matches/${encodeURIComponent(matchUuid)}/forecast`);
}
