import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  async rewrites() {
    // /api/c/[client_id]/chat/stream is handled by the Route Handler in
    // app/api/c/[client_id]/chat/stream/route.ts so it is intentionally absent.
    // Dynamic routes are evaluated after afterFiles rewrites, so a wildcard
    // /api/:path* rewrite would shadow the route handler in the standalone build.
    return [
      {
        source: "/healthz",
        destination: `${process.env.API_URL ?? "http://localhost:8000"}/healthz`,
      },
    ];
  },
};

export default nextConfig;
