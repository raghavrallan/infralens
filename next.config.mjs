import path from "path";
import { fileURLToPath } from "url";

const root = path.dirname(fileURLToPath(import.meta.url));

/** @type {import('next').NextConfig} */
const nextConfig = {
  turbopack: {
    root,
  },
  // The dev server is opened as localhost, 127.0.0.1, and the Ubuntu server's
  // LAN address. Without this, Next blocks the HMR websocket and the login
  // form falls back to a reload. ALLOWED_DEV_ORIGINS is a comma-separated
  // list of extra hostnames (no scheme, no port), set by start-suite.sh.
  allowedDevOrigins: [
    ...new Set(
      ["127.0.0.1", "localhost", "100.86.171.3", "10.8.18.111"].concat(
        (process.env.ALLOWED_DEV_ORIGINS || "")
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean),
      ),
    ),
  ],
  agentRules: false,
};

export default nextConfig;
