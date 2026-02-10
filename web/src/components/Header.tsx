"use client";

import { useState } from "react";
import Link from "next/link";
import { useAuth } from "@/context/AuthContext";
import { TelegramLogin } from "./TelegramLogin";

const TELEGRAM_BOT_NAME = process.env.NEXT_PUBLIC_TELEGRAM_BOT_NAME || "";
const ENABLE_DEV_LOGIN = process.env.NEXT_PUBLIC_ENABLE_DEV_LOGIN === "true";

export function Header() {
  const { user, loading, login, devLogin, logout } = useAuth();
  const [showLoginModal, setShowLoginModal] = useState(false);

  return (
    <>
      <header className="border-b border-[var(--border)] bg-[var(--surface)]">
        <div className="mx-auto flex h-12 max-w-5xl items-center justify-between px-4">
          {/* Logo */}
          <Link href="/" className="flex items-center gap-2 text-[var(--foreground)] hover:text-[var(--primary)]">
            <span className="text-[var(--primary)] animate-pulse">❯</span>
            <span className="text-lg font-bold tracking-tight">distill</span>
          </Link>

          {/* Auth */}
          <div className="flex items-center gap-3">
            {loading ? (
              <div className="h-6 w-16 animate-pulse rounded bg-[var(--border)]" />
            ) : user ? (
              <div className="flex items-center gap-3">
                <span className="text-[var(--foreground-secondary)]">
                  {user.display_name || user.username}
                </span>
                <button onClick={logout} className="terminal-btn text-xs">
                  logout
                </button>
              </div>
            ) : (
              <button
                onClick={() => setShowLoginModal(true)}
                className="terminal-btn terminal-btn-primary text-xs"
              >
                login
              </button>
            )}
          </div>
        </div>
      </header>

      {/* Login Modal */}
      {showLoginModal && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
          onClick={() => setShowLoginModal(false)}
        >
          <div
            className="terminal-card w-full max-w-sm p-6"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-4 flex items-center justify-between">
              <h2 className="font-semibold text-[var(--foreground)]">Login</h2>
              <button
                onClick={() => setShowLoginModal(false)}
                className="text-[var(--muted)] hover:text-[var(--foreground)]"
              >
                ✕
              </button>
            </div>

            {TELEGRAM_BOT_NAME ? (
              <div className="mb-4">
                <p className="mb-3 text-[var(--muted)]">
                  Sign in with Telegram to vote on posts
                </p>
                <TelegramLogin
                  botName={TELEGRAM_BOT_NAME}
                  onAuth={async (data) => {
                    await login(data);
                    setShowLoginModal(false);
                  }}
                />
              </div>
            ) : null}

            {!TELEGRAM_BOT_NAME && ENABLE_DEV_LOGIN && (
              <div className="border-t border-[var(--border)] pt-4">
                <p className="mb-3 text-[var(--muted)]">Development mode:</p>
                <button
                  onClick={async () => {
                    await devLogin();
                    setShowLoginModal(false);
                  }}
                  className="terminal-btn w-full justify-center"
                >
                  dev login
                </button>
              </div>
            )}

            {!TELEGRAM_BOT_NAME && !ENABLE_DEV_LOGIN && (
              <div className="border-t border-[var(--border)] pt-4">
                <p className="text-[var(--muted)]">
                  Telegram login is not configured.
                </p>
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
}
