import type { NextConfig } from "next";

const isDev = process.env.NODE_ENV === "development";
const apiOrigin = process.env.DEV_API_ORIGIN || "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  // Static export is for production / FastAPI serving frontend/out.
  // In `next dev`, skip export so HMR + API rewrites work.
  ...(isDev ? {} : { output: "export" as const }),
  trailingSlash: true,
  images: { unoptimized: true },
  turbopack: { root: __dirname },
  async rewrites() {
    if (!isDev) return [];
    return [
      {
        source: "/api/:path*",
        destination: `${apiOrigin}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
