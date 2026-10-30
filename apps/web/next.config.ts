import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Shared API types and client live in packages/shared_ts as TypeScript source.
  transpilePackages: ["@scanassist/shared"],
  output: "standalone",
};

export default nextConfig;
