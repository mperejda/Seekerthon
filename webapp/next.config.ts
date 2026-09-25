import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  webpack: (config) => {
    // Some Solana packages reference Node builtins that don't exist in the browser
    config.resolve.fallback = { fs: false, path: false, os: false };
    return config;
  },
  async rewrites() {
    // Keep browser requests and session cookies on the web app's origin.
    const backend = (process.env.BACKEND_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000")
      .replace(/\/+$/, "").replace(/\/api\/v1$/, "");
    return [
      {
        // FastAPI's collection route requires the slash. Resolve it internally
        // so its redirect never sends the browser to the backend's origin.
        source: "/api/v1/hackathons",
        destination: `${backend}/api/v1/hackathons/`,
      },
      {
        source: "/api/v1/:path*",
        destination: `${backend}/api/v1/:path*`,
      },
    ];
  },
};

export default nextConfig;
