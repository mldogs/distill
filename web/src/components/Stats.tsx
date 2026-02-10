"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Stats as StatsType } from "@/types";

interface StatsProps {
  period?: string;
}

export function Stats({ period = "weekly" }: StatsProps) {
  const [stats, setStats] = useState<StatsType | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadStats();

    const handleRefresh = () => loadStats();
    window.addEventListener("admin-refresh", handleRefresh);
    return () => window.removeEventListener("admin-refresh", handleRefresh);
  }, [period]);

  async function loadStats() {
    setLoading(true);
    try {
      const data = await api.getStats(period);
      setStats(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load stats");
    } finally {
      setLoading(false);
    }
  }

  if (loading) {
    return (
      <div className="mb-6 grid grid-cols-2 gap-4 md:grid-cols-4">
        {[1, 2, 3, 4].map((i) => (
          <div
            key={i}
            className="terminal-card h-16 animate-pulse p-3"
          />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="terminal-card mb-6 p-4 text-[var(--danger)]">
        <span className="mr-2">✗</span>
        {error}
      </div>
    );
  }

  if (!stats) return null;

  const periodLabel = period === "daily" ? "24h" : period === "monthly" ? "30d" : period === "all" ? "all" : "7d";

  return (
    <div className="mb-6">
      {/* Stats grid */}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <div className="terminal-card p-4">
          <div className="text-xs text-[var(--muted)]">channels</div>
          <div className="text-xl font-semibold text-[var(--foreground)]">
            {stats.channels_count}
          </div>
        </div>

        <div className="terminal-card p-4">
          <div className="text-xs text-[var(--muted)]">posts ({periodLabel})</div>
          <div className="text-xl font-semibold text-[var(--foreground)]">
            {stats.posts_count.toLocaleString()}
          </div>
        </div>

        <div className="terminal-card p-4">
          <div className="text-xs text-[var(--muted)]">avg proof</div>
          <div className="text-xl font-semibold text-[var(--foreground)]">
            {stats.avg_score.toFixed(1)}
          </div>
        </div>

        <div className="terminal-card p-4">
          <div className="text-xs text-[var(--muted)]">votes</div>
          <div className="text-xl font-semibold text-[var(--foreground)]">
            {stats.votes_count.toLocaleString()}
          </div>
        </div>
      </div>
    </div>
  );
}
