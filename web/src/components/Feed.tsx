"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { FeedParams, FeedSortBy, FeedSortDir, Post } from "@/types";
import { PostCard } from "./PostCard";

interface FeedProps {
  period?: string;
  formula?: string;
  limit?: number;
  min_views?: number;
  min_replies?: number;
  min_reactions?: number;
  min_forwards?: number;
  min_novelty?: number;
  sort_by?: FeedSortBy;
  sort_dir?: FeedSortDir;
}

export function Feed({
  period = "weekly",
  formula = "v4",
  limit = 10,
  min_views,
  min_replies,
  min_reactions,
  min_forwards,
  min_novelty,
  sort_by,
  sort_dir,
}: FeedProps) {
  const [posts, setPosts] = useState<Post[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadFeed(true);

    const handleRefresh = () => loadFeed(false);
    window.addEventListener("admin-refresh", handleRefresh);
    return () => window.removeEventListener("admin-refresh", handleRefresh);
  }, [period, formula, limit, min_views, min_replies, min_reactions, min_forwards, min_novelty, sort_by, sort_dir]);

  async function loadFeed(showLoading = true) {
    if (showLoading) {
      setLoading(true);
    }
    setError(null);

    try {
      const params: FeedParams = {
        period,
        formula,
        limit,
        min_views,
        min_replies,
        min_reactions,
        min_forwards,
        min_novelty,
        sort_by,
        sort_dir,
      };
      const response = await api.getFeed(params);
      setPosts(response.posts);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load feed");
    } finally {
      if (showLoading) {
        setLoading(false);
      }
    }
  }

  if (loading) {
    return (
      <div className="space-y-4">
        {[1, 2, 3, 4, 5].map((i) => (
          <div
            key={i}
            className="terminal-card h-28 animate-pulse p-4"
          >
            <div className="flex gap-4">
              <div className="h-6 w-6 rounded bg-[var(--border)]" />
              <div className="flex-1 space-y-2">
                <div className="h-3 w-1/3 rounded bg-[var(--border)]" />
                <div className="h-3 w-full rounded bg-[var(--border)]" />
                <div className="h-3 w-2/3 rounded bg-[var(--border)]" />
              </div>
            </div>
          </div>
        ))}
        <div className="text-center text-xs text-[var(--muted)]">
          loading<span className="cursor-blink"></span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="terminal-card p-8 text-center">
        <p className="mb-4 text-[var(--danger)]">
          error: {error}
        </p>
        <button
          onClick={() => loadFeed(true)}
          className="terminal-btn"
        >
          retry
        </button>
      </div>
    );
  }

  if (posts.length === 0) {
    return (
      <div className="terminal-card p-8 text-center">
        <p className="mb-2 text-[var(--muted)]">
          no posts found
        </p>
        <p className="text-xs text-[var(--muted)]">
          try a different period or run the pipeline
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {/* Feed header */}
      <div className="flex items-center justify-between text-xs text-[var(--muted)]">
        <span>
          showing <span className="text-[var(--foreground)]">{posts.length}</span> posts
        </span>
        <span>
          {period} / {formula}
        </span>
      </div>

      {/* Posts */}
      {posts.map((post, index) => (
        <PostCard key={post.id} post={post} rank={index + 1} />
      ))}

      {/* End marker */}
      <div className="py-4 text-center text-xs text-[var(--muted)]">
        -- end --
      </div>
    </div>
  );
}
