import { proxyBackend } from "@/lib/backend-proxy";
import { rateLimited } from "@/lib/rate-limited-route";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  return rateLimited(request, () => proxyBackend("/api/setup/status"));
}
