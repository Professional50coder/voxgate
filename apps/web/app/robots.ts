import type { MetadataRoute } from "next";

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "https://voxgate.app";

/**
 * The product surfaces are disallowed rather than merely unlinked. /console,
 * /dashboard and /admin display applicant data, and /apply/* will carry
 * per-case tokens once tokenized links land. None of that belongs in an index.
 */
export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: "/",
        disallow: ["/console", "/dashboard", "/admin", "/api/"],
      },
    ],
    sitemap: `${SITE_URL}/sitemap.xml`,
    host: SITE_URL,
  };
}
