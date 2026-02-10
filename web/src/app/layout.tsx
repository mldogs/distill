import type { Metadata } from "next";
import { JetBrains_Mono } from "next/font/google";
import Script from "next/script";
import "./globals.css";
import { Header } from "@/components/Header";
import { AuthProvider } from "@/context/AuthContext";
import { PostHogProvider } from "@/context/PostHogProvider";

const mono = JetBrains_Mono({
  subsets: ["latin", "cyrillic"],
  variable: "--font-mono",
});

export const metadata: Metadata = {
  title: "Distill — The Finest from Telegram",
  description: "Лучшее из Telegram, очищенное от шума. Ежедневная дистилляция контента из сотен каналов в одну ленту.",
  keywords: ["telegram", "агрегатор", "дайджест", "новости", "каналы", "подборка", "distill", "лучшее из telegram"],
  authors: [{ name: "nlp_daily", url: "https://t.me/nlp_daily" }],
  creator: "nlp_daily",
  metadataBase: new URL("https://tgdistill.space"),
  openGraph: {
    type: "website",
    locale: "ru_RU",
    url: "https://tgdistill.space",
    siteName: "Distill",
    title: "Distill — The Finest from Telegram",
    description: "Лучшее из Telegram, очищенное от шума. Ежедневная дистилляция контента из сотен каналов.",
  },
  twitter: {
    card: "summary_large_image",
    title: "Distill — The Finest from Telegram",
    description: "Лучшее из Telegram, очищенное от шума. Дистилляция контента из сотен каналов.",
  },
  robots: {
    index: true,
    follow: true,
    googleBot: {
      index: true,
      follow: true,
      "max-video-preview": -1,
      "max-image-preview": "large",
      "max-snippet": -1,
    },
  },
  alternates: {
    canonical: "https://tgdistill.space",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ru">
      <head>
        <Script
          src="https://analytics.tgdistill.space/script.js"
          data-website-id="00cb6912-28b4-49be-8182-117b13f25e4e"
          strategy="afterInteractive"
        />
      </head>
      <body className={`${mono.variable} font-[family-name:var(--font-mono)] text-sm antialiased`}>
        <PostHogProvider>
        <AuthProvider>
          <div className="flex min-h-screen flex-col bg-[var(--background)]">
            <Header />
            <div className="flex-1">{children}</div>
            <footer className="border-t border-[var(--border)] py-6">
              <div className="mx-auto max-w-5xl px-4">
                <div className="flex flex-col items-center gap-3 text-xs text-[var(--muted)]">
                  <div className="flex items-center gap-2">
                    <span className="text-[var(--primary)]">❯</span>
                    <span>distill — the finest from telegram</span>
                  </div>
                  <a
                    href="https://t.me/nlp_daily"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-2 text-[var(--muted)] hover:text-[var(--primary)] transition-colors"
                  >
                    <img
                      src="https://unavatar.io/telegram/nlp_daily"
                      alt="@nlp_daily"
                      className="h-5 w-5 rounded-full"
                    />
                    <span>made by @nlp_daily</span>
                  </a>
                  <div className="flex flex-col items-center gap-1.5 pt-2 text-[10px]">
                    <span>support the project</span>
                    <div className="flex flex-wrap justify-center gap-x-4 gap-y-1">
                      <span className="flex items-center gap-1">
                        <span className="text-[var(--foreground)]">ETH</span>
                        <code className="select-all text-[var(--muted)]">0xfFA9383Dd3e43D308B25b436dB0dc30418937e23</code>
                      </span>
                      <span className="flex items-center gap-1">
                        <span className="text-[var(--foreground)]">BTC</span>
                        <code className="select-all text-[var(--muted)]">bc1qy8vqgzxltzkwktq5l48savp2vfe9z5f8qkaf82</code>
                      </span>
                    </div>
                  </div>
                </div>
              </div>
            </footer>
          </div>
        </AuthProvider>
        </PostHogProvider>
      </body>
    </html>
  );
}
