"use client";

import { Suspense, useState, useRef, useEffect } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { Stats } from "@/components/Stats";
import { FilterBar } from "@/components/FilterBar";
import { Feed } from "@/components/Feed";
import { Abyss } from "@/components/Abyss";
import { SearchResults } from "@/components/SearchResults";
import type { FeedSortBy, FeedSortDir } from "@/types";

function HomeContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);

  const period = searchParams.get("period") || "weekly";
  const view = ((searchParams.get("view") as "top" | "abyss") || "top") satisfies "top" | "abyss";

  const allowedSortBy: FeedSortBy[] = ["score", "posted_at", "views", "replies", "reactions", "forwards", "novelty"];
  const allowedSortDir: FeedSortDir[] = ["desc", "asc"];

  const sort_by_param = searchParams.get("sort_by");
  const sort_dir_param = searchParams.get("sort_dir");
  const sort_by: FeedSortBy = allowedSortBy.includes(sort_by_param as FeedSortBy)
    ? (sort_by_param as FeedSortBy)
    : "score";
  const sort_dir: FeedSortDir = allowedSortDir.includes(sort_dir_param as FeedSortDir)
    ? (sort_dir_param as FeedSortDir)
    : "desc";

  function parseMinInt(key: string): number | null {
    const raw = searchParams.get(key);
    if (!raw) return null;
    const n = parseInt(raw, 10);
    if (!Number.isFinite(n) || n <= 0) return null;
    return n;
  }

  function parseMinFloat01(key: string): number | null {
    const raw = searchParams.get(key);
    if (!raw) return null;
    const n = parseFloat(raw);
    if (!Number.isFinite(n) || n <= 0) return null;
    return Math.min(1, n);
  }

  const min_views = parseMinInt("min_views");
  const min_replies = parseMinInt("min_replies");
  const min_reactions = parseMinInt("min_reactions");
  const min_forwards = parseMinInt("min_forwards");
  const min_novelty = parseMinFloat01("min_novelty");

  // Search state — URL-driven for bookmarkability
  const searchQuery = searchParams.get("q") || "";
  const [searchDraft, setSearchDraft] = useState(searchQuery);

  // Sync draft when URL changes externally
  useEffect(() => {
    setSearchDraft(searchQuery);
  }, [searchQuery]);

  const isSearchMode = searchQuery.length > 0;

  function updateUrl(next: Partial<{
    period: string;
    view: "top" | "abyss";
    sort_by: FeedSortBy;
    sort_dir: FeedSortDir;
    min_views: number | null;
    min_replies: number | null;
    min_reactions: number | null;
    min_forwards: number | null;
    min_novelty: number | null;
    q: string;
  }>) {
    const merged = {
      period,
      view,
      sort_by,
      sort_dir,
      min_views,
      min_replies,
      min_reactions,
      min_forwards,
      min_novelty,
      q: searchQuery,
      ...next,
    };

    const params = new URLSearchParams();
    if (merged.q) params.set("q", merged.q);
    if (merged.period !== "weekly") params.set("period", merged.period);
    if (merged.view !== "top") params.set("view", merged.view);
    if (merged.sort_by !== "score") params.set("sort_by", merged.sort_by);
    if (merged.sort_dir !== "desc") params.set("sort_dir", merged.sort_dir);
    if ((merged.min_views ?? 0) > 0) params.set("min_views", String(merged.min_views));
    if ((merged.min_replies ?? 0) > 0) params.set("min_replies", String(merged.min_replies));
    if ((merged.min_reactions ?? 0) > 0) params.set("min_reactions", String(merged.min_reactions));
    if ((merged.min_forwards ?? 0) > 0) params.set("min_forwards", String(merged.min_forwards));
    if ((merged.min_novelty ?? 0) > 0) params.set("min_novelty", String(merged.min_novelty));
    const query = params.toString();
    router.push(query ? `/?${query}` : "/", { scroll: false });
  }

  function handlePeriodChange(newPeriod: string) {
    updateUrl({ period: newPeriod });
  }

  function handleViewChange(newView: "top" | "abyss") {
    updateUrl({ view: newView });
  }

  function handleSearchSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = searchDraft.trim();
    updateUrl({ q: trimmed });
  }

  function handleSearchClear() {
    setSearchDraft("");
    updateUrl({ q: "" });
    inputRef.current?.focus();
  }

  // Keyboard shortcut: / to focus search
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (
        e.key === "/" &&
        !e.ctrlKey &&
        !e.metaKey &&
        document.activeElement?.tagName !== "INPUT" &&
        document.activeElement?.tagName !== "TEXTAREA" &&
        document.activeElement?.tagName !== "SELECT"
      ) {
        e.preventDefault();
        inputRef.current?.focus();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  return (
    <main className="mx-auto max-w-6xl px-4 py-8">
      {/* Stats */}
      <div className="mb-8">
        <Stats period={period} />
      </div>

      {/* Search */}
      <div className="mb-6">
        <form onSubmit={handleSearchSubmit} className="relative">
          <input
            ref={inputRef}
            type="text"
            value={searchDraft}
            onChange={(e) => setSearchDraft(e.target.value)}
            placeholder="search posts..."
            className="terminal-input w-full py-2.5 pl-8 pr-20 text-sm"
          />
          <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[var(--muted)]">
            &gt;
          </span>
          <div className="absolute right-2 top-1/2 flex -translate-y-1/2 items-center gap-1">
            {searchDraft && (
              <button
                type="button"
                onClick={handleSearchClear}
                className="px-2 py-1 text-xs text-[var(--muted)] hover:text-[var(--foreground)]"
                title="Clear search"
              >
                esc
              </button>
            )}
            <button
              type="submit"
              className="terminal-btn terminal-btn-primary px-3 py-1 text-xs"
            >
              search
            </button>
          </div>
        </form>
      </div>

      {/* Filters (hidden in search mode) */}
      {!isSearchMode && (
        <div className="mb-6">
          <FilterBar
            period={period}
            onPeriodChange={handlePeriodChange}
            view={view}
            onViewChange={handleViewChange}
            sort_by={sort_by}
            sort_dir={sort_dir}
            min_views={min_views}
            min_replies={min_replies}
            min_reactions={min_reactions}
            min_forwards={min_forwards}
            min_novelty={min_novelty}
            onChange={updateUrl}
          />
        </div>
      )}

      {/* Search results or Feed/Abyss */}
      {isSearchMode ? (
        <SearchResults query={searchQuery} mode="hybrid" />
      ) : view === "top" ? (
        <Feed
          period={period}
          formula="v4"
          limit={10}
          sort_by={sort_by}
          sort_dir={sort_dir}
          min_views={min_views ?? undefined}
          min_replies={min_replies ?? undefined}
          min_reactions={min_reactions ?? undefined}
          min_forwards={min_forwards ?? undefined}
          min_novelty={min_novelty ?? undefined}
        />
      ) : (
        <Abyss
          period={period}
          formula="v4"
          sort_by={sort_by}
          sort_dir={sort_dir}
          min_views={min_views ?? undefined}
          min_replies={min_replies ?? undefined}
          min_reactions={min_reactions ?? undefined}
          min_forwards={min_forwards ?? undefined}
          min_novelty={min_novelty ?? undefined}
        />
      )}
    </main>
  );
}

export default function Home() {
  return (
    <Suspense
      fallback={
        <main className="mx-auto max-w-6xl px-4 py-8">
          <div className="space-y-4">
            {[1, 2, 3].map((i) => (
              <div
                key={i}
                className="h-20 animate-pulse rounded-lg bg-[var(--card)]"
              />
            ))}
          </div>
        </main>
      }
    >
      <HomeContent />
    </Suspense>
  );
}
