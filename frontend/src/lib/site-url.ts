const LOCAL_SITE_URL = "http://localhost:3000";

export function resolveSiteUrl(
  configured = process.env.PREM_ENGINE_SITE_URL,
  deploymentEnvironment = process.env.VERCEL_ENV,
): URL {
  if (!configured) {
    if (deploymentEnvironment === "production") {
      throw new Error("PREM_ENGINE_SITE_URL is required for production deployments");
    }
    return new URL(LOCAL_SITE_URL);
  }

  const siteUrl = new URL(configured);
  if (
    siteUrl.username ||
    siteUrl.password ||
    siteUrl.pathname !== "/" ||
    siteUrl.search ||
    siteUrl.hash
  ) {
    throw new Error("PREM_ENGINE_SITE_URL must be a public origin without credentials or suffixes");
  }
  if (deploymentEnvironment === "production" && siteUrl.protocol !== "https:") {
    throw new Error("PREM_ENGINE_SITE_URL must use HTTPS in production");
  }
  return siteUrl;
}
