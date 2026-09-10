import type { NextConfig } from "next";
import { buildSecurityHeaders } from "./lib/webSecurity";

const securityHeaders = buildSecurityHeaders({
  environment: process.env.NODE_ENV ?? "development",
  apiBaseUrl:
    process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000",
  enableHsts: process.env.ENABLE_HSTS === "true",
});

const nextConfig: NextConfig = {
  productionBrowserSourceMaps: false,
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
  turbopack: {
    root: process.cwd(),
  },
};

export default nextConfig;
