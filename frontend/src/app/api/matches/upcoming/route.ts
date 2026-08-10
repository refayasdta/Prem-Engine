import { proxyBackend } from "@/lib/backend-proxy";

export const dynamic = "force-dynamic";

export async function GET() {
  return proxyBackend("/api/matches/upcoming?limit=10");
}
