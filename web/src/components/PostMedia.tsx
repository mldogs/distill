"use client";

import { useState } from "react";

interface PostMediaProps {
  permalink: string;
  mediaType: string;
  hasText: boolean;
  isExpanded?: boolean;
}

/**
 * Extracts channel username and message ID from permalink.
 * Example: https://t.me/durov/123 -> { channel: "durov", messageId: "123" }
 */
function parsePermalink(permalink: string): { channel: string; messageId: string } | null {
  const match = permalink.match(/t\.me\/([^/]+)\/(\d+)/);
  if (!match) return null;
  return { channel: match[1], messageId: match[2] };
}

/**
 * Get human-readable media type label.
 */
function getMediaLabel(mediaType: string): string {
  const typeMap: Record<string, string> = {
    MessageMediaPhoto: "photo",
    MessageMediaDocument: "file",
    MessageMediaVideo: "video",
    MessageMediaWebPage: "link",
    MessageMediaGeo: "location",
    MessageMediaPoll: "poll",
    MessageMediaContact: "contact",
  };
  return typeMap[mediaType] || mediaType.replace("MessageMedia", "").toLowerCase();
}

export function PostMedia({ permalink, mediaType, hasText, isExpanded = false }: PostMediaProps) {
  const [manualToggle, setManualToggle] = useState<boolean | null>(null);
  const [embedLoaded, setEmbedLoaded] = useState(false);

  const parsed = parsePermalink(permalink);
  if (!parsed) return null;

  const embedUrl = `https://t.me/${parsed.channel}/${parsed.messageId}?embed=1&mode=tme`;
  const mediaLabel = getMediaLabel(mediaType);

  // Determine if embed should be shown:
  // - If manually toggled, use that value
  // - If post is expanded (user clicked [more]), show media
  // - If no text (media-only post), show media
  const shouldShow = manualToggle !== null ? manualToggle : (isExpanded || !hasText);

  if (!shouldShow) {
    return (
      <div className="mb-3">
        <button
          onClick={() => setManualToggle(true)}
          className="text-xs text-[var(--primary)] hover:text-[var(--primary-hover)]"
        >
          [show {mediaLabel}]
        </button>
      </div>
    );
  }

  return (
    <div className="mb-3">
      <div
        className={`overflow-hidden rounded border border-[var(--border)] transition-opacity ${
          embedLoaded ? "opacity-100" : "opacity-50"
        }`}
      >
        {!embedLoaded && (
          <div className="flex h-48 items-center justify-center bg-[var(--surface)]">
            <span className="text-sm text-[var(--muted)]">loading {mediaLabel}...</span>
          </div>
        )}
        <iframe
          src={embedUrl}
          className="w-full"
          style={{
            height: embedLoaded ? "auto" : "0",
            minHeight: embedLoaded ? "200px" : "0",
            border: "none"
          }}
          onLoad={() => setEmbedLoaded(true)}
          sandbox="allow-scripts allow-same-origin allow-popups"
        />
      </div>
      {hasText && (
        <button
          onClick={() => setManualToggle(false)}
          className="mt-1 text-xs text-[var(--muted)] hover:text-[var(--foreground)]"
        >
          [hide media]
        </button>
      )}
    </div>
  );
}
