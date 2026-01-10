import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Enable standalone output for optimized Docker builds
  // This creates a minimal production bundle without node_modules
  output: "standalone",
};

export default nextConfig;
