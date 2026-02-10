"use client";

import { useState } from "react";
import { usePostHog } from "posthog-js/react";
import type { Post } from "@/types";
import { VoteButtons } from "./VoteButtons";
import { ScoreExplainer } from "./ScoreExplainer";
import { MarkdownText } from "./MarkdownText";
import { PostMedia } from "./PostMedia";

interface PostCardProps {
  post: Post;
  rank: number;
}

function formatNumber(num: number | undefined): string {
  if (num === undefined || num === null) return "-";
  if (num >= 1000000) return `${(num / 1000000).toFixed(1)}M`;
  if (num >= 1000) return `${(num / 1000).toFixed(1)}K`;
  return num.toString();
}

function timeAgo(dateString: string): string {
  const now = new Date();
  const date = new Date(dateString);
  const seconds = Math.floor((now.getTime() - date.getTime()) / 1000);

  if (seconds < 60) return "now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h`;
  if (seconds < 604800) return `${Math.floor(seconds / 86400)}d`;
  return date.toLocaleDateString("ru-RU", { day: "numeric", month: "short" });
}

const MAX_COLLAPSED_LENGTH = 200;

export function PostCard({ post, rank }: PostCardProps) {
  const posthog = usePostHog();
  const [isExpanded, setIsExpanded] = useState(false);

  const text = post.text || "";
  const isLongText = text.length > MAX_COLLAPSED_LENGTH;
  const displayText = isExpanded || !isLongText
    ? text
    : text.slice(0, MAX_COLLAPSED_LENGTH).trim() + "...";

  const hasHighEssence = post.novelty_score !== undefined && post.novelty_score >= 0.7;

  return (
    <div className="terminal-card overflow-hidden p-4 transition-all">
      <div className="flex gap-3 sm:gap-4">
        {/* Rank + Vote */}
        <div className="flex flex-col items-center">
          <span className="text-sm font-medium text-[var(--primary)]">
            #{rank}
          </span>
          <div className="my-2 h-px w-4 bg-[var(--border)]" />
          <VoteButtons postId={post.id} />
        </div>

        {/* Main content */}
        <div className="min-w-0 flex-1">
          {/* Header */}
          <div className="mb-2 flex flex-wrap items-center gap-2 text-sm">
            <a
              href={`https://t.me/${post.channel.username}`}
              target="_blank"
              rel="noopener noreferrer"
              className="font-medium text-[var(--foreground)] hover:text-[var(--primary)]"
            >
              @{post.channel.username}
            </a>
            {post.channel.name && (
              <span className="hidden text-[var(--muted)] sm:inline">
                {post.channel.name}
              </span>
            )}
            <span className="text-[var(--muted)]">
              {timeAgo(post.posted_at)}
            </span>

            {/* Essence badge */}
            {hasHighEssence && (
              <span className="terminal-badge ml-auto">
                {post.novelty_score! >= 0.9 ? "✨ pure" : "💧 fresh"}
              </span>
            )}
          </div>

          {/* Text content */}
          {text && (
            <div className="mb-3">
              <div className="whitespace-pre-wrap break-words leading-relaxed text-[var(--foreground-secondary)]">
                <MarkdownText>{displayText}</MarkdownText>
              </div>

              {isLongText && (
                <button
                  onClick={() => setIsExpanded(!isExpanded)}
                  className="mt-2 text-xs text-[var(--primary)] hover:text-[var(--primary-hover)]"
                >
                  [{isExpanded ? "less" : "more"}]
                </button>
              )}
            </div>
          )}

          {/* Media content */}
          {post.media_type && (
            <PostMedia
              permalink={post.permalink}
              mediaType={post.media_type}
              hasText={!!text}
              isExpanded={isExpanded}
            />
          )}

          {/* Metrics row */}
          <div className="flex flex-wrap items-center gap-4 text-xs text-[var(--muted)]">
            <span title="Views">
              {formatNumber(post.views)} views
            </span>
            <span title="Forwards">
              {formatNumber(post.forwards)} fwd
            </span>
            <span className="hidden sm:inline" title="Replies">
              {formatNumber(post.replies)} replies
            </span>
            <span title="Reactions">
              {formatNumber(post.reactions_count)} reactions
            </span>

            {/* Essence indicator */}
            {post.novelty_score !== undefined && post.novelty_score !== null && (
              <span
                title={`Essence: ${(post.novelty_score * 100).toFixed(0)}% unique information`}
                className={
                  post.novelty_score >= 0.7
                    ? "text-[var(--primary)]"
                    : ""
                }
              >
                ✨ {(post.novelty_score * 100).toFixed(0)}%
              </span>
            )}

            {/* Score */}
            <div className="ml-auto">
              <ScoreExplainer score={post.score} />
            </div>

            {/* Link to post */}
            <a
              href={post.permalink}
              target="_blank"
              rel="noopener noreferrer"
              className="text-[var(--primary)] hover:text-[var(--primary-hover)]"
              onClick={() => posthog?.capture("post_click", {
                post_id: post.id,
                channel: post.channel.username,
                rank,
              })}
            >
              [open]
            </a>
          </div>
        </div>
      </div>
    </div>
  );
}
