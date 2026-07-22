import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  webpack: (config) => {
    // Some Solana packages reference Node builtins that don't exist in the browser
    config.resolve.fallback = { fs: false, path: false, os: false };
    return config;
  },
  async rewrites() {
    const backend = process.env.BACKEND_URL ?? "http://localhost:8000";
    return [
      {
        source: "/api/v1/:path*",
        destination: `${backend}/api/v1/:path*`,
      },
    ];
  },
};

export default nextConfig;
