"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { FeedParams, FeedSortBy, FeedSortDir, Post } from "@/types";
import { PostCard } from "./PostCard";

interface AbyssProps {
  period?: string;
  formula?: string;
  min_views?: number;
  min_replies?: number;
  min_reactions?: number;
  min_forwards?: number;
  min_novelty?: number;
  sort_by?: FeedSortBy;
  sort_dir?: FeedSortDir;
}

const PAGE_SIZE = 10;
const TOP_POSTS_OFFSET = 10; // Skip top 10 posts

export function Abyss({
  period = "weekly",
  formula = "v4",
  min_views,
  min_replies,
  min_reactions,
  min_forwards,
  min_novelty,
  sort_by,
  sort_dir,
}: AbyssProps) {
  const [posts, setPosts] = useState<Post[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(0);
  const [totalPosts, setTotalPosts] = useState(0);
  const [hasMore, setHasMore] = useState(false);

  useEffect(() => {
    setPage(0);
    loadPage(0, true);

    const handleRefresh = () => loadPage(0, false);
    window.addEventListener("admin-refresh", handleRefresh);
    return () => window.removeEventListener("admin-refresh", handleRefresh);
  }, [period, formula, min_views, min_replies, min_reactions, min_forwards, min_novelty, sort_by, sort_dir]);

  async function loadPage(pageNum: number, showLoading = true) {
    if (showLoading) {
      setLoading(true);
    }
    setError(null);

    try {
      const offset = TOP_POSTS_OFFSET + pageNum * PAGE_SIZE;
      const params: FeedParams = {
        period,
        formula,
        limit: PAGE_SIZE,
        offset,
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
      setTotalPosts(response.total);
      // Check if there are more posts after current page
      setHasMore(offset + response.posts.length < response.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load feed");
    } finally {
      if (showLoading) {
        setLoading(false);
      }
    }
  }

  function handlePrevPage() {
    if (page > 0) {
      const newPage = page - 1;
      setPage(newPage);
      loadPage(newPage);
    }
  }

  function handleNextPage() {
    if (hasMore) {
      const newPage = page + 1;
      setPage(newPage);
      loadPage(newPage);
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
          descending into the abyss<span className="cursor-blink"></span>
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
          onClick={() => loadPage(page, true)}
          className="terminal-btn"
        >
          retry
        </button>
      </div>
    );
  }

  const abyssTotal = Math.max(0, totalPosts - TOP_POSTS_OFFSET);

  if (posts.length === 0) {
    return (
      <div className="terminal-card p-8 text-center">
        <p className="mb-2 text-[var(--muted)]">
          the abyss is empty
        </p>
        <p className="text-xs text-[var(--muted)]">
          all posts made it to the top
        </p>
      </div>
    );
  }

  const startRank = TOP_POSTS_OFFSET + page * PAGE_SIZE + 1;

  return (
    <div className="space-y-3">
      {/* Abyss header */}
      <div className="flex items-center justify-between text-xs text-[var(--muted)]">
        <span>
          <span className="text-[var(--foreground)]">{abyssTotal}</span> posts in the abyss
        </span>
        <span>
          page {page + 1} / {Math.ceil(abyssTotal / PAGE_SIZE)}
        </span>
      </div>

      {/* Posts */}
      {posts.map((post, index) => (
        <PostCard key={post.id} post={post} rank={startRank + index} />
      ))}

      {/* Pagination */}
      <div className="flex items-center justify-center gap-4 py-4">
        <button
          onClick={handlePrevPage}
          disabled={page === 0}
          className={`terminal-btn px-4 py-2 text-sm ${
            page === 0 ? "opacity-50 cursor-not-allowed" : ""
          }`}
        >
          prev
        </button>
        <span className="text-xs text-[var(--muted)]">
          {startRank}-{startRank + posts.length - 1} of {totalPosts}
        </span>
        <button
          onClick={handleNextPage}
          disabled={!hasMore}
          className={`terminal-btn px-4 py-2 text-sm ${
            !hasMore ? "opacity-50 cursor-not-allowed" : ""
          }`}
        >
          next
        </button>
      </div>
    </div>
  );
}
