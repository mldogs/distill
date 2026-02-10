"use client";

import { useEffect, useState, useCallback } from "react";
import { api } from "@/lib/api";
import type { SearchResponse } from "@/types";
import { PostCard } from "./PostCard";

interface SearchResultsProps {
  query: string;
  mode?: "lexical" | "semantic" | "hybrid";
}

const PAGE_SIZE = 20;

export function SearchResults({ query, mode = "lexical" }: SearchResultsProps) {
  const [data, setData] = useState<SearchResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(0);

  const doSearch = useCallback(
    async (pageNum: number, showLoading = true) => {
      if (!query.trim()) return;
      if (showLoading) setLoading(true);
      setError(null);

      try {
        const result = await api.search({
          q: query,
          mode,
          limit: PAGE_SIZE,
          offset: pageNum * PAGE_SIZE,
        });
        setData(result);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Search failed");
      } finally {
        if (showLoading) setLoading(false);
      }
    },
    [query, mode]
  );

  useEffect(() => {
    setPage(0);
    doSearch(0);
  }, [query, mode, doSearch]);

  function handlePrevPage() {
    if (page > 0) {
      const newPage = page - 1;
      setPage(newPage);
      doSearch(newPage);
    }
  }

  function handleNextPage() {
    if (data && (page + 1) * PAGE_SIZE < data.total) {
      const newPage = page + 1;
      setPage(newPage);
      doSearch(newPage);
    }
  }

  if (loading) {
    return (
      <div className="space-y-4">
        {[1, 2, 3].map((i) => (
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
          searching<span className="cursor-blink"></span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="terminal-card p-8 text-center">
        <p className="mb-4 text-[var(--danger)]">error: {error}</p>
        <button onClick={() => doSearch(page)} className="terminal-btn">
          retry
        </button>
      </div>
    );
  }

  if (!data || data.results.length === 0) {
    return (
      <div className="terminal-card p-8 text-center">
        <p className="mb-2 text-[var(--muted)]">no results found</p>
        <p className="text-xs text-[var(--muted)]">
          try a different query or fewer filters
        </p>
      </div>
    );
  }

  const hasMore = (page + 1) * PAGE_SIZE < data.total;
  const totalPages = Math.ceil(data.total / PAGE_SIZE);

  return (
    <div className="space-y-3">
      {/* Search header */}
      <div className="flex items-center justify-between text-xs text-[var(--muted)]">
        <span>
          <span className="text-[var(--foreground)]">{data.total}</span> results
          {data.took_ms !== undefined && (
            <> in <span className="text-[var(--foreground)]">{data.took_ms}ms</span></>
          )}
        </span>
        <span>
          mode: {data.mode}
          {totalPages > 1 && <> &middot; page {page + 1}/{totalPages}</>}
        </span>
      </div>

      {/* Results */}
      {data.results.map((result, index) => (
        <div key={result.post.id} className="relative">
          <PostCard
            post={result.post}
            rank={page * PAGE_SIZE + index + 1}
          />
        </div>
      ))}

      {/* Pagination */}
      {totalPages > 1 && (
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
            {page * PAGE_SIZE + 1}-
            {Math.min((page + 1) * PAGE_SIZE, data.total)} of {data.total}
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
      )}
    </div>
  );
}
