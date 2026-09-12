import path from "path";
import type { NextConfig } from "next";

const isDev = process.env.NODE_ENV === "development";
const apiOrigin = (process.env.DEV_API_ORIGIN || process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8000").replace(
  /\/$/,
  "",
);

// Pin Turbopack to this app dir. A package-lock.json in the user home directory
// otherwise becomes the inferred root and Turbopack panics with
// "Next.js package not found", which also makes /login/ request-loop in dev.
const appRoot = path.resolve(__dirname);

const nextConfig: NextConfig = {
  // Static export is for production / FastAPI serving frontend/out.
  // In `next dev`, skip export so HMR works. Rewrites are also incompatible
  // with `output: "export"` (see nextjs.org/docs/messages/export-no-custom-routes).
  trailingSlash: true,
  images: { unoptimized: true },
  turbopack: { root: appRoot },
};

if (isDev) {
  nextConfig.rewrites = async () => [
    { source: "/c/:chatId", destination: "/?chat=:chatId" },
    { source: "/c/:chatId/", destination: "/?chat=:chatId" },
    { source: "/api/:path*/", destination: `${apiOrigin}/api/:path*` },
    { source: "/api/:path*", destination: `${apiOrigin}/api/:path*` },
  ];
} else {
  nextConfig.output = "export";
}

export default nextConfig;
