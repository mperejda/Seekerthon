import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  webpack: (config) => {
    // Some Solana packages reference Node builtins that don't exist in the browser
    config.resolve.fallback = { fs: false, path: false, os: false };
    return config;
  },
};

export default nextConfig;
