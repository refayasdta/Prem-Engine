import { proxyBackend } from "@/lib/backend-proxy";

export async function GET(request: Request) {
  return proxyBackend(`/api/standings${new URL(request.url).search}`);
}
