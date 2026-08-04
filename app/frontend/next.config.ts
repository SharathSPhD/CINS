import type { NextConfig } from "next";

// Backend origin (FastAPI, `uvicorn app.main:app --port 8000` from
// app/backend — see app/README.md). Overridable for non-local dev.
const BACKEND_ORIGIN = process.env.CINS_BACKEND_ORIGIN ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${BACKEND_ORIGIN}/api/:path*` },
      { source: "/health", destination: `${BACKEND_ORIGIN}/health` },
    ];
  },
};

export default nextConfig;
