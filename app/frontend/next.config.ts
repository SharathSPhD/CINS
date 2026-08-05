import type { NextConfig } from "next";

// Backend origin (FastAPI, `uvicorn app.main:app --port 8000` from
// app/backend — see app/README.md). NEXT_PUBLIC_API_BASE is the
// deploy-readiness env var (app/README.md "Deploy"); CINS_BACKEND_ORIGIN is
// kept as a back-compat alias. Falls back to localhost:8000 for local dev.
const BACKEND_ORIGIN =
  process.env.NEXT_PUBLIC_API_BASE ?? process.env.CINS_BACKEND_ORIGIN ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${BACKEND_ORIGIN}/api/:path*` },
      { source: "/health", destination: `${BACKEND_ORIGIN}/health` },
      { source: "/static/:path*", destination: `${BACKEND_ORIGIN}/static/:path*` },
    ];
  },
};

export default nextConfig;
