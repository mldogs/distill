"use client";

import { useEffect, useRef } from "react";
import type { TelegramAuthData } from "@/types";

interface TelegramLoginProps {
  botName: string;
  onAuth: (data: TelegramAuthData) => void;
  buttonSize?: "large" | "medium" | "small";
  cornerRadius?: number;
  showUserPhoto?: boolean;
}

declare global {
  interface Window {
    TelegramLoginWidget?: {
      dataOnauth?: (user: TelegramAuthData) => void;
    };
  }
}

export function TelegramLogin({
  botName,
  onAuth,
  buttonSize = "large",
  cornerRadius = 8,
  showUserPhoto = true,
}: TelegramLoginProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // Set up global callback
    window.TelegramLoginWidget = {
      dataOnauth: (user: TelegramAuthData) => {
        onAuth(user);
      },
    };

    // Create script element
    const script = document.createElement("script");
    script.src = "https://telegram.org/js/telegram-widget.js?22";
    script.setAttribute("data-telegram-login", botName);
    script.setAttribute("data-size", buttonSize);
    script.setAttribute("data-radius", cornerRadius.toString());
    script.setAttribute("data-onauth", "TelegramLoginWidget.dataOnauth(user)");
    script.setAttribute("data-request-access", "write");
    if (showUserPhoto) {
      script.setAttribute("data-userpic", "true");
    }
    script.async = true;

    // Append to container
    if (containerRef.current) {
      containerRef.current.innerHTML = "";
      containerRef.current.appendChild(script);
    }

    return () => {
      delete window.TelegramLoginWidget;
    };
  }, [botName, buttonSize, cornerRadius, showUserPhoto, onAuth]);

  return <div ref={containerRef} className="telegram-login-container" />;
}
