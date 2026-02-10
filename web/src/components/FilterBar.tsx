"use client";

import { useState } from "react";
import { usePostHog } from "posthog-js/react";
import type { FeedSortBy, FeedSortDir } from "@/types";

interface FilterBarProps {
  period: string;
  onPeriodChange: (period: string) => void;
  view: "top" | "abyss";
  onViewChange: (view: "top" | "abyss") => void;
  sort_by: FeedSortBy;
  sort_dir: FeedSortDir;
  min_views: number | null;
  min_replies: number | null;
  min_reactions: number | null;
  min_forwards: number | null;
  min_novelty: number | null;
  onChange: (next: Partial<{
    sort_by: FeedSortBy;
    sort_dir: FeedSortDir;
    min_views: number | null;
    min_replies: number | null;
    min_reactions: number | null;
    min_forwards: number | null;
    min_novelty: number | null;
  }>) => void;
}

const PERIODS = [
  { value: "daily", label: "day" },
  { value: "weekly", label: "week" },
  { value: "monthly", label: "month" },
  { value: "all", label: "all" },
];

const VIEWS = [
  { value: "top", label: "top 10" },
  { value: "abyss", label: "abyss" },
];

const SORT_FIELDS: Array<{ value: FeedSortBy; label: string }> = [
  { value: "score", label: "score" },
  { value: "views", label: "views" },
  { value: "novelty", label: "essence" },
  { value: "reactions", label: "reactions" },
  { value: "replies", label: "replies" },
  { value: "forwards", label: "forwards" },
  { value: "posted_at", label: "time" },
];

const SORT_DIRS: Array<{ value: FeedSortDir; label: string }> = [
  { value: "desc", label: "desc" },
  { value: "asc", label: "asc" },
];

const DEFAULT_FILTER_PARAMS = {
  sort_dir: "desc" as FeedSortDir,
  min_views: null,
  min_replies: null,
  min_reactions: null,
  min_forwards: null,
  min_novelty: null,
};

const PRESETS: Array<{ id: string; label: string; params: typeof DEFAULT_FILTER_PARAMS & { sort_by: FeedSortBy } }> = [
  { id: "score", label: "score", params: { ...DEFAULT_FILTER_PARAMS, sort_by: "score" } },
  { id: "essence", label: "essence", params: { ...DEFAULT_FILTER_PARAMS, sort_by: "novelty" } },
  { id: "reach", label: "reach", params: { ...DEFAULT_FILTER_PARAMS, sort_by: "views" } },
  { id: "discussion", label: "discussion", params: { ...DEFAULT_FILTER_PARAMS, sort_by: "replies" } },
  { id: "liked", label: "liked", params: { ...DEFAULT_FILTER_PARAMS, sort_by: "reactions" } },
  { id: "viral", label: "viral", params: { ...DEFAULT_FILTER_PARAMS, sort_by: "forwards" } },
];

interface ButtonGroupProps {
  options: { value: string; label: string }[];
  value: string;
  onChange: (value: string) => void;
  label?: string;
}

function ButtonGroup({ options, value, onChange, label }: ButtonGroupProps) {
  return (
    <div className="flex items-center gap-2">
      {label && (
        <span className="text-xs text-[var(--muted)]">{label}</span>
      )}
      <div className="flex gap-1">
        {options.map((option) => {
          const isActive = option.value === value;
          return (
            <button
              key={option.value}
              onClick={() => onChange(option.value)}
              className={`
                px-3 py-1.5 text-xs transition-all rounded
                ${isActive
                  ? 'bg-[var(--primary)] text-white'
                  : 'bg-[var(--surface)] text-[var(--muted)] hover:bg-[var(--background-secondary)] hover:text-[var(--foreground)] border border-[var(--border)]'
                }
              `}
            >
              {option.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

export function FilterBar({
  period,
  onPeriodChange,
  view,
  onViewChange,
  sort_by,
  sort_dir,
  min_views,
  min_replies,
  min_reactions,
  min_forwards,
  min_novelty,
  onChange,
}: FilterBarProps) {
  const posthog = usePostHog();

  const canReset =
    sort_by !== "score" ||
    sort_dir !== "desc" ||
    (min_views ?? 0) > 0 ||
    (min_replies ?? 0) > 0 ||
    (min_reactions ?? 0) > 0 ||
    (min_forwards ?? 0) > 0 ||
    (min_novelty ?? 0) > 0;

  const [showAdvanced, setShowAdvanced] = useState<boolean>(canReset);
  const [isEditingNovelty, setIsEditingNovelty] = useState(false);
  const [minNoveltyDraft, setMinNoveltyDraft] = useState<string>("");

  const handlePeriodChange = (newPeriod: string) => {
    posthog?.capture("filter_change", {
      filter_type: "period",
      old_value: period,
      new_value: newPeriod,
    });
    onPeriodChange(newPeriod);
  };

  const handleViewChange = (newView: string) => {
    posthog?.capture("filter_change", {
      filter_type: "view",
      old_value: view,
      new_value: newView,
    });
    onViewChange(newView as "top" | "abyss");
  };

  const handleSortByChange = (value: string) => {
    posthog?.capture("filter_change", {
      filter_type: "sort_by",
      old_value: sort_by,
      new_value: value,
    });
    onChange({ sort_by: value as FeedSortBy });
  };

  const handleSortDirChange = (value: string) => {
    posthog?.capture("filter_change", {
      filter_type: "sort_dir",
      old_value: sort_dir,
      new_value: value,
    });
    onChange({ sort_dir: value as FeedSortDir });
  };

  const handleMinChange = (
    key: "min_views" | "min_replies" | "min_reactions" | "min_forwards",
    value: string
  ) => {
    const n = value === "" ? null : parseInt(value, 10);
    const parsed = n !== null && Number.isFinite(n) && n > 0 ? n : null;
    posthog?.capture("filter_change", {
      filter_type: key,
      old_value:
        key === "min_views"
          ? min_views
          : key === "min_replies"
            ? min_replies
            : key === "min_reactions"
              ? min_reactions
              : min_forwards,
      new_value: parsed,
    });
    if (key === "min_views") onChange({ min_views: parsed });
    else if (key === "min_replies") onChange({ min_replies: parsed });
    else if (key === "min_reactions") onChange({ min_reactions: parsed });
    else onChange({ min_forwards: parsed });
  };

  const commitMinNoveltyDraft = () => {
    const raw = minNoveltyDraft.trim();
    if (!raw) {
      onChange({ min_novelty: null });
      return;
    }
    const parsed = Number.parseFloat(raw.replace(",", "."));
    if (!Number.isFinite(parsed)) {
      onChange({ min_novelty: null });
      return;
    }
    const clamped = Math.min(1, Math.max(0, parsed));
    onChange({ min_novelty: clamped > 0 ? clamped : null });
  };

  const handleMinNoveltyBlur = () => {
    const prev = min_novelty;
    commitMinNoveltyDraft();
    setIsEditingNovelty(false);
    posthog?.capture("filter_change", {
      filter_type: "min_novelty",
      old_value: prev,
      new_value: minNoveltyDraft,
    });
    // Sync input to canonical URL-derived value on next render.
  };

  const handleMinNoveltyKeyDown: React.KeyboardEventHandler<HTMLInputElement> = (e) => {
    if (e.key === "Enter") {
      (e.target as HTMLInputElement).blur();
    }
  };

  const handleMinNoveltyChange = (value: string) => setMinNoveltyDraft(value);
  const handleMinNoveltyFocus = () => {
    setIsEditingNovelty(true);
    setMinNoveltyDraft(min_novelty !== null ? String(min_novelty) : "");
  };

  const activePresetId =
    PRESETS.find(
      (p) =>
        p.params.sort_by === sort_by &&
        p.params.sort_dir === sort_dir &&
        p.params.min_views === min_views &&
        p.params.min_replies === min_replies &&
        p.params.min_reactions === min_reactions &&
        p.params.min_forwards === min_forwards &&
        p.params.min_novelty === min_novelty
    )?.id ?? null;

  const applyPreset = (presetId: string) => {
    const preset = PRESETS.find((p) => p.id === presetId);
    if (!preset) return;
    posthog?.capture("filter_change", {
      filter_type: "preset",
      old_value: activePresetId ?? "custom",
      new_value: presetId,
    });
    onChange(preset.params);
  };

  const summaryParts: string[] = [];
  if (sort_by !== "score" || sort_dir !== "desc") {
    const sortLabel =
      sort_by === "score"
        ? "score"
        : sort_by === "posted_at"
          ? "time"
          : sort_by === "reactions"
            ? "react"
            : sort_by === "replies"
              ? "repl"
              : sort_by === "forwards"
                ? "fwd"
                : sort_by === "novelty"
                  ? "essence"
                  : "views";
    summaryParts.push(`${sortLabel}${sort_dir === "desc" ? "↓" : "↑"}`);
  }
  // Intentionally hide numeric thresholds in the collapsed summary to reduce UI noise.

  return (
    <div className="terminal-card space-y-2 p-3">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <ButtonGroup
          options={VIEWS}
          value={view}
          onChange={handleViewChange}
          label="view:"
        />
        <ButtonGroup
          options={PERIODS}
          value={period}
          onChange={handlePeriodChange}
          label="period:"
        />
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-[var(--muted)]">presets:</span>
          <div className="flex flex-wrap gap-1">
            {PRESETS.map((p) => {
              const isActive = p.id === activePresetId;
              return (
                <button
                  key={p.id}
                  onClick={() => applyPreset(p.id)}
                  className={`
                    px-3 py-1.5 text-xs transition-all rounded
                    ${isActive
                      ? 'bg-[var(--primary)] text-white'
                      : 'bg-[var(--surface)] text-[var(--muted)] hover:bg-[var(--background-secondary)] hover:text-[var(--foreground)] border border-[var(--border)]'
                    }
                  `}
                  title={`preset: ${p.label}`}
                >
                  {p.label}
                </button>
              );
            })}
          </div>
        </div>
        {activePresetId !== null && activePresetId !== "score" && (
          <span className="text-xs text-[var(--muted)]">
            active: <span className="text-[var(--foreground)]">{activePresetId}</span>
          </span>
        )}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <button
            onClick={() => setShowAdvanced((v) => !v)}
            className="terminal-btn text-xs"
            title={showAdvanced ? "Hide advanced filters" : "Show advanced filters"}
          >
            filters
          </button>
          {!showAdvanced && summaryParts.length > 0 && (
            <span className="text-xs text-[var(--muted)]">
              {summaryParts.join(" • ")}
            </span>
          )}
        </div>
        {!showAdvanced && (
          <button
            onClick={() =>
              onChange({
                sort_by: "score",
                sort_dir: "desc",
                min_views: null,
                min_replies: null,
                min_reactions: null,
                min_forwards: null,
                min_novelty: null,
              })
            }
            className={`terminal-btn text-xs ${canReset ? "" : "opacity-50 cursor-not-allowed"}`}
            disabled={!canReset}
            title="Reset filters"
          >
            reset
          </button>
        )}
      </div>

      {showAdvanced && (
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div className="flex flex-wrap items-end gap-2">
            <span className="text-xs text-[var(--muted)]">sort:</span>
            <select
              value={sort_by}
              onChange={(e) => handleSortByChange(e.target.value)}
              className="terminal-select text-sm"
              title="Sort field"
            >
              {SORT_FIELDS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
            <select
              value={sort_dir}
              onChange={(e) => handleSortDirChange(e.target.value)}
              className="terminal-select text-sm"
              title="Sort direction"
            >
              {SORT_DIRS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </div>

          <div className="flex flex-wrap items-end gap-2">
            <span className="text-xs text-[var(--muted)]">min:</span>
            <input
              type="number"
              min={0}
              value={min_views ?? ""}
              onChange={(e) => handleMinChange("min_views", e.target.value)}
              className="terminal-input w-24 text-sm"
              placeholder="views"
              title="Minimum views"
            />
            <input
              type="number"
              min={0}
              value={min_reactions ?? ""}
              onChange={(e) => handleMinChange("min_reactions", e.target.value)}
              className="terminal-input w-24 text-sm"
              placeholder="react"
              title="Minimum reactions"
            />
            <input
              type="number"
              min={0}
              value={min_replies ?? ""}
              onChange={(e) => handleMinChange("min_replies", e.target.value)}
              className="terminal-input w-24 text-sm"
              placeholder="repl"
              title="Minimum replies"
            />
            <input
              type="number"
              min={0}
              value={min_forwards ?? ""}
              onChange={(e) => handleMinChange("min_forwards", e.target.value)}
              className="terminal-input w-24 text-sm"
              placeholder="fwd"
              title="Minimum forwards"
            />
            <input
              type="text"
              inputMode="decimal"
              value={isEditingNovelty ? minNoveltyDraft : (min_novelty !== null ? String(min_novelty) : "")}
              onChange={(e) => handleMinNoveltyChange(e.target.value)}
              onFocus={handleMinNoveltyFocus}
              onBlur={handleMinNoveltyBlur}
              onKeyDown={handleMinNoveltyKeyDown}
              className="terminal-input w-24 text-sm"
              placeholder="essence (0..1)"
              title="Minimum essence (0..1), press Enter to apply"
            />
            <button
              onClick={() =>
                onChange({
                  sort_by: "score",
                  sort_dir: "desc",
                  min_views: null,
                  min_replies: null,
                  min_reactions: null,
                  min_forwards: null,
                  min_novelty: null,
                })
              }
              className={`terminal-btn text-xs ${canReset ? "" : "opacity-50 cursor-not-allowed"}`}
              disabled={!canReset}
              title="Reset filters"
            >
              reset
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
