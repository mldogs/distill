import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Output standalone build for Docker
  output: "standalone",

  // Environment variables available at build time
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000",
  },

  // Security headers for Telegram embed
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          {
            key: "Content-Security-Policy",
            value: [
              "default-src 'self'",
              "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://telegram.org https://analytics.tgdistill.space",
              "style-src 'self' 'unsafe-inline'",
              "img-src 'self' data: blob: https:",
              "font-src 'self'",
              "connect-src *",
              "frame-src https://t.me https://telegram.org https://oauth.telegram.org",
            ].join("; "),
          },
        ],
      },
    ];
  },
};

export default nextConfig;
