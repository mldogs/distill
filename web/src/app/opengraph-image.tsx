import { ImageResponse } from "next/og";

export const runtime = "edge";

export const alt = "Distill — The Finest from Telegram";
export const size = {
  width: 1200,
  height: 630,
};
export const contentType = "image/png";

export default async function Image() {
  return new ImageResponse(
    (
      <div
        style={{
          height: "100%",
          width: "100%",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          backgroundColor: "#0a0a0a",
          fontFamily: "monospace",
        }}
      >
        {/* Background pattern */}
        <div
          style={{
            position: "absolute",
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            backgroundImage:
              "radial-gradient(circle at 25% 25%, #1a1a2e 0%, transparent 50%), radial-gradient(circle at 75% 75%, #16213e 0%, transparent 50%)",
            opacity: 0.5,
          }}
        />

        {/* Main content */}
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 1,
          }}
        >
          {/* Logo/Icon */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              marginBottom: 32,
            }}
          >
            <div
              style={{
                width: 80,
                height: 80,
                borderRadius: 16,
                background: "linear-gradient(135deg, #667eea 0%, #764ba2 100%)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontSize: 48,
                color: "white",
              }}
            >
              D
            </div>
          </div>

          {/* Title */}
          <div
            style={{
              fontSize: 72,
              fontWeight: 700,
              color: "#ffffff",
              marginBottom: 16,
              letterSpacing: "-2px",
            }}
          >
            Distill
          </div>

          {/* Subtitle */}
          <div
            style={{
              fontSize: 32,
              color: "#a78bfa",
              marginBottom: 40,
            }}
          >
            The Finest from Telegram
          </div>

          {/* Description */}
          <div
            style={{
              fontSize: 24,
              color: "#9ca3af",
              textAlign: "center",
              maxWidth: 800,
              lineHeight: 1.4,
            }}
          >
            Лучшее из Telegram, очищенное от шума
          </div>

          {/* Terminal prompt decoration */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              marginTop: 48,
              fontSize: 20,
              color: "#6b7280",
            }}
          >
            <span style={{ color: "#a78bfa", marginRight: 8 }}>❯</span>
            <span>tgdistill.space</span>
          </div>
        </div>
      </div>
    ),
    {
      ...size,
    }
  );
}
