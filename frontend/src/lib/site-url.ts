const LOCAL_SITE_URL = "http://localhost:3000";

export function resolveSiteUrl(
  configured = process.env.PREM_ENGINE_SITE_URL,
): URL {
  if (!configured) {
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
  return siteUrl;
}
