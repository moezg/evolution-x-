import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Static export: FastAPI serves web/out at the same origin as /api.
  output: "export",
  trailingSlash: false,
  images: { unoptimized: true },
  reactStrictMode: true,
};

export default nextConfig;
