import type { NextConfig } from "next";

/**
 * The browser never talks to the API directly. It calls same-origin `/api/*`,
 * and this rewrite forwards to the real backend.
 *
 * Two problems disappear as a result, both of which had already bitten:
 *
 *  1. `NEXT_PUBLIC_*` is inlined at BUILD time. A deployment that set the API
 *     URL after building would still ship a bundle pointing at
 *     `127.0.0.1:8000`, so every visitor's browser would call their own
 *     machine and fail in a way that looks like the backend being down.
 *     `API_ORIGIN` is read here, on the server, at start — so changing it is a
 *     restart, not a rebuild.
 *
 *  2. Same-origin means no CORS preflight at all. CORS misconfiguration is the
 *     single failure that has cost the most time on this project, and this
 *     removes the category rather than documenting it.
 *
 * Dev and production now take the identical path, so a CORS or URL problem
 * cannot appear for the first time in production.
 */
const API_ORIGIN = (process.env.API_ORIGIN ?? "http://127.0.0.1:8000").replace(/\/+$/, "");

const nextConfig: NextConfig = {
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_ORIGIN}/:path*` }];
  },
};

export default nextConfig;
