import type { NextConfig } from "next";

const isDev = process.env.NODE_ENV === "development";
const apiOrigin = (process.env.DEV_API_ORIGIN || process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8000").replace(
  /\/$/,
  "",
);

const nextConfig: NextConfig = {
  // Static export is for production / FastAPI serving frontend/out.
  // In `next dev`, skip export so HMR works.
  ...(isDev ? {} : { output: "export" as const }),
  trailingSlash: true,
  images: { unoptimized: true },
  turbopack: { root: __dirname },
  // Keep rewrites as a fallback; local UI primarily uses NEXT_PUBLIC_API_BASE.
  async rewrites() {
    if (!isDev) return [];
    return [
      { source: "/api/:path*/", destination: `${apiOrigin}/api/:path*` },
      { source: "/api/:path*", destination: `${apiOrigin}/api/:path*` },
    ];
  },
};

export default nextConfig;
