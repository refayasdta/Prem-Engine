import { proxyBackend } from "@/lib/backend-proxy";
import { rateLimited } from "@/lib/rate-limited-route";

export async function GET(request: Request) {
  return rateLimited(request, () =>
    proxyBackend(`/api/evaluation${new URL(request.url).search}`),
  );
}
