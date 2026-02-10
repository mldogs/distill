"use client";

import { useState, useRef, useEffect } from "react";
import { api } from "@/lib/api";
import type { ChannelInfo } from "@/types";

interface TaskState {
  id: string;
  status: string;
  message?: string;
}

interface LogEntry {
  time: string;
  type: "info" | "success" | "error" | "pending";
  message: string;
}

interface AdminPanelProps {
  defaultExpanded?: boolean;
}

export function AdminPanel({ defaultExpanded = false }: AdminPanelProps) {
  const [isExpanded, setIsExpanded] = useState(defaultExpanded);
  const [channel, setChannel] = useState("@nobilix");
  const [sinceDays, setSinceDays] = useState(7);
  const [messageLimit, setMessageLimit] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [task, setTask] = useState<TaskState | null>(null);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [showBulkImport, setShowBulkImport] = useState(false);
  const [bulkChannels, setBulkChannels] = useState("");
  const [bulkAutoRank, setBulkAutoRank] = useState(true);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [showChannels, setShowChannels] = useState(false);
  const [channels, setChannels] = useState<ChannelInfo[]>([]);
  const [targetMode, setTargetMode] = useState<"single" | "selected" | "all">("single");
  const [selectedUsernames, setSelectedUsernames] = useState<string[]>([]);
  const [channelSearch, setChannelSearch] = useState("");
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [refreshInterval] = useState(30);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);
  const [rankFormula, setRankFormula] = useState("v4");
  const [rankPeriod, setRankPeriod] = useState<"daily" | "weekly" | "monthly">("daily");
  const [pipelinePeriod, setPipelinePeriod] = useState<"daily" | "weekly" | "monthly">("daily");
  const [noveltyHours, setNoveltyHours] = useState(48);
  const [noveltyContextDays, setNoveltyContextDays] = useState(30);
  const [noveltyForce, setNoveltyForce] = useState(false);
  const [noveltyAllowLargeBackfill, setNoveltyAllowLargeBackfill] = useState(false);
  const [openrouterConfigured, setOpenrouterConfigured] = useState<boolean | null>(null);
  const logEndRef = useRef<HTMLDivElement>(null);

  // Ingestion mode controls
  const [ingestionMode, setIngestionMode] = useState<"window" | "incremental" | "refresh_recent">("window");

  // Collector settings (read-only display)
  const [graceMins, setGraceMins] = useState<number | null>(null);
  const [refreshHours, setRefreshHours] = useState<number | null>(null);

  // Settings & Profiling
  const [showSettings, setShowSettings] = useState(false);
  const [showProfiling, setShowProfiling] = useState(false);
  const [showHelp, setShowHelp] = useState(false);
  const [settings, setSettings] = useState<Record<string, number | string | boolean>>({});
  const [settingsLoading, setSettingsLoading] = useState(false);
  const [profilingStats, setProfilingStats] = useState<Record<string, {
    count: number;
    avg_duration_ms: number;
    max_duration_ms: number;
    success_rate?: number;
  }>>({});
  const [profilingTotalRuns, setProfilingTotalRuns] = useState(0);

  function addLog(type: LogEntry["type"], message: string) {
    const time = new Date().toLocaleTimeString("en-US", { hour12: false });
    setLogs((prev) => [...prev.slice(-20), { time, type, message }]);
  }

  function sanitizeChannel(input: string): string {
    return input.replace("@", "").trim().split(/\s+/)[0] || "";
  }

  function getTargetChannels(): string[] | null {
    if (targetMode === "all") return null;
    if (targetMode === "single") {
      const clean = sanitizeChannel(channel);
      return clean ? [clean] : [];
    }
    return selectedUsernames;
  }

  async function handleAddAndCollect() {
    setLoading(true);
    const targetChannels = getTargetChannels();
    const targetLabel =
      targetChannels === null
        ? "(all channels)"
        : targetChannels.length === 1
          ? `@${targetChannels[0]}`
          : `(${targetChannels.length} channels)`;
    addLog("info", `> sync ${targetLabel} --mode=${ingestionMode} --days=${sinceDays}${messageLimit ? ` --limit=${messageLimit}` : ""}`);

    try {
      if (targetChannels === null) {
        const result = await api.triggerCollect({
          mode: ingestionMode,
          since_days: sinceDays,
          limit: messageLimit ?? undefined,
        });
        setTask({ id: result.task_id || "", status: result.status, message: result.message });
        addLog("pending", result.message);
        if (result.task_id) pollTaskStatus(result.task_id);
        return;
      }

      if (targetChannels.length === 0) {
        addLog("error", targetMode === "single" ? "Invalid channel username" : "No channels selected");
        return;
      }

      const result = await api.ingestChannels({
        channels: targetChannels,
        mode: ingestionMode,
        since_days: sinceDays,
        limit: messageLimit ?? undefined,
        auto_rank: false,
      });

      setTask({ id: result.task_id, status: result.status, message: result.message });
      addLog("pending", `Task ${result.task_id.slice(0, 8)}... started`);
      pollTaskStatus(result.task_id);
    } catch (err) {
      addLog("error", err instanceof Error ? err.message : "Failed");
    } finally {
      setLoading(false);
    }
  }

  async function handlePipeline() {
    setLoading(true);
    const pipelineDays = pipelinePeriod === "daily" ? 1 : pipelinePeriod === "weekly" ? 7 : 30;
    const targetChannels = getTargetChannels();
    const targetLabel =
      targetChannels === null
        ? "(all channels)"
        : targetChannels.length === 1
          ? `@${targetChannels[0]}`
          : `(${targetChannels.length} channels)`;
    addLog(
      "info",
      `> pipeline ${targetLabel} --period=${pipelinePeriod} --fetch-days=${pipelineDays} --novelty-hours=${noveltyHours} --context=${noveltyContextDays} --formula=${rankFormula}`,
    );

    try {
      const result = await api.triggerPipeline({
        since_days: pipelineDays,
        with_novelty: openrouterConfigured !== false,
        novelty_limit: 100,
        novelty_analysis_hours: noveltyHours,
        novelty_context_days: noveltyContextDays,
        allow_large_novelty_backfill: noveltyHours > 168 ? noveltyAllowLargeBackfill : false,
        rank_periods: [pipelinePeriod],
        fetch_mode: "refresh_recent",
        channels: targetChannels === null ? undefined : targetChannels,
      });
      setTask({ id: result.pipeline_id, status: result.status, message: result.message });
      addLog("pending", result.message);
      pollTaskStatus(result.pipeline_id);
    } catch (err) {
      addLog("error", err instanceof Error ? err.message : "Failed");
    } finally {
      setLoading(false);
    }
  }

  async function handleNovelty() {
    setLoading(true);
    const targetChannels = getTargetChannels();
    const targetLabel =
      targetChannels === null
        ? "(all channels)"
        : targetChannels.length === 1
          ? `@${targetChannels[0]}`
          : `(${targetChannels.length} channels)`;
    addLog("info", `> novelty ${targetLabel} --hours=${noveltyHours} --context=${noveltyContextDays}${noveltyForce ? " --force" : ""}`);

    try {
      const result = await api.triggerNovelty({
        analysisHours: noveltyHours,
        contextDays: noveltyContextDays,
        force: noveltyForce,
        allowLargeBackfill: noveltyHours > 168 ? noveltyAllowLargeBackfill : false,
        channels: targetChannels === null ? undefined : targetChannels,
      });
      setTask({ id: result.task_id, status: result.status, message: `Novelty for last ${noveltyHours}h${noveltyForce ? " (force)" : ""}` });
      addLog("pending", `Task ${result.task_id.slice(0, 8)}... started`);
      pollTaskStatus(result.task_id);
    } catch (err) {
      addLog("error", err instanceof Error ? err.message : "Failed");
    } finally {
      setLoading(false);
    }
  }

  async function handleRank() {
    setLoading(true);
    addLog("info", `> rank --period=${rankPeriod} --formula=${rankFormula}`);

    try {
      addLog("pending", `Ranking ${rankPeriod}...`);
      const result = await api.triggerRank({
        period: rankPeriod,
        formula: rankFormula,
      });
      setTask({ id: result.task_id, status: result.status, message: `Ranking ${rankPeriod}` });
      addLog("pending", `Task ${result.task_id.slice(0, 8)}... started`);
      pollTaskStatus(result.task_id);
    } catch (err) {
      addLog("error", err instanceof Error ? err.message : "Failed");
    } finally {
      setLoading(false);
    }
  }

  async function pollTaskStatus(taskId: string) {
    const pollIntervalMs = 2000;
    const maxMinutes = 30;
    const maxAttempts = Math.floor((maxMinutes * 60 * 1000) / pollIntervalMs);
    let attempts = 0;

    const poll = async () => {
      if (attempts >= maxAttempts) {
        addLog("error", `Stopped polling after ${maxMinutes}m (task may still be running)`);
        setTask((prev) => (prev ? { ...prev, status: "timeout", message: "stopped polling (still running?)" } : null));
        return;
      }

      try {
        const status = await api.getTaskStatus(taskId);
        setTask({ id: taskId, status: status.status, message: status.error || status.status });

        if (status.status === "SUCCESS") {
          addLog("success", `Task completed: ${JSON.stringify(status.result).slice(0, 50)}...`);
        } else if (status.status === "FAILURE") {
          addLog("error", `Task failed: ${status.error}`);
        } else {
          attempts++;
          setTimeout(poll, pollIntervalMs);
        }
      } catch {
        attempts++;
        setTimeout(poll, pollIntervalMs);
      }
    };

    poll();
  }

  function handleFileUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (event) => setBulkChannels(event.target?.result as string);
    reader.readAsText(file);
  }

  async function handleBulkImport() {
    const lines = bulkChannels.split(/[\n,]+/).map((l) => l.trim()).filter((l) => l.length > 0);
    if (lines.length === 0) {
      addLog("error", "No channels to import");
      return;
    }

    setLoading(true);
    addLog("info", `> ingest --count=${lines.length} --mode=${ingestionMode} --days=${sinceDays}${messageLimit ? ` --limit=${messageLimit}` : ""}`);

    try {
      const result = await api.ingestChannels({
        channels: lines,
        mode: ingestionMode,
        since_days: sinceDays,
        limit: messageLimit ?? undefined,
        auto_rank: bulkAutoRank,
      });
      setTask({ id: result.task_id, status: result.status, message: result.message });
      addLog("pending", result.message);
      pollTaskStatus(result.task_id);
      setBulkChannels("");
      setShowBulkImport(false);
    } catch (err) {
      addLog("error", err instanceof Error ? err.message : "Failed");
    } finally {
      setLoading(false);
    }
  }

  async function loadChannels() {
    try {
      const data = await api.listChannels();
      setChannels(data);
      if (selectedUsernames.length > 0) {
        const known = new Set(data.map((c) => c.username));
        setSelectedUsernames((prev) => prev.filter((u) => known.has(u)));
      }
    } catch (err) {
      addLog("error", err instanceof Error ? err.message : "Failed to load channels");
    }
  }

  async function loadSettings() {
    setSettingsLoading(true);
    try {
      const data = await api.getSettings();
      setSettings(data.settings);

      // Extract collector settings for display
      const grace = data.settings["collector.incremental_grace_minutes"];
      const refresh = data.settings["collector.refresh_recent_hours"];
      setGraceMins(typeof grace === "number" ? grace : null);
      setRefreshHours(typeof refresh === "number" ? refresh : null);
    } catch (err) {
      addLog("error", err instanceof Error ? err.message : "Failed to load settings");
    } finally {
      setSettingsLoading(false);
    }
  }

  async function handleUpdateSetting(key: string, value: number | string | boolean) {
    try {
      await api.updateSettings({ [key]: value });
      setSettings((prev) => ({ ...prev, [key]: value }));
      addLog("success", `Updated ${key} = ${value}`);
    } catch (err) {
      addLog("error", err instanceof Error ? err.message : "Failed to update setting");
    }
  }

  async function loadProfiling() {
    try {
      const data = await api.getProfilingStats(7);
      setProfilingStats(data.by_task);
      setProfilingTotalRuns(data.total_runs);
    } catch (err) {
      addLog("error", err instanceof Error ? err.message : "Failed to load profiling");
    }
  }

  async function handleToggleChannel(channelId: number, currentActive: boolean) {
    try {
      await api.toggleChannel(channelId, !currentActive);
      setChannels((prev) => prev.map((ch) => (ch.id === channelId ? { ...ch, is_active: !currentActive } : ch)));
      addLog("success", `Channel ${channelId} ${currentActive ? "disabled" : "enabled"}`);
    } catch (err) {
      addLog("error", err instanceof Error ? err.message : "Failed");
    }
  }

  async function handleDeleteChannel(channelId: number, username: string) {
    if (!confirm(`Delete @${username} and all its posts?`)) return;
    try {
      await api.deleteChannel(channelId);
      setChannels((prev) => prev.filter((ch) => ch.id !== channelId));
      addLog("success", `Deleted @${username}`);
    } catch (err) {
      addLog("error", err instanceof Error ? err.message : "Failed");
    }
  }

  useEffect(() => {
    if (showChannels && channels.length === 0) loadChannels();
  }, [showChannels]);

  useEffect(() => {
    async function loadConfig() {
      try {
        const config = await api.getAdminConfig();
        setOpenrouterConfigured(config.openrouter_configured);

        // Load collector settings
        const settingsData = await api.getSettings();
        const grace = settingsData.settings["collector.incremental_grace_minutes"];
        const refresh = settingsData.settings["collector.refresh_recent_hours"];
        setGraceMins(typeof grace === "number" ? grace : null);
        setRefreshHours(typeof refresh === "number" ? refresh : null);
      } catch {
        // Ignore - user might not be admin yet
      }
    }
    loadConfig();
  }, []);

  useEffect(() => {
    if (!autoRefresh) return;
    const interval = setInterval(() => {
      window.dispatchEvent(new CustomEvent("admin-refresh"));
      setLastRefresh(new Date());
    }, refreshInterval * 1000);
    window.dispatchEvent(new CustomEvent("admin-refresh"));
    setLastRefresh(new Date());
    return () => clearInterval(interval);
  }, [autoRefresh, refreshInterval]);

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs]);

  // Collapsed state
  if (!isExpanded) {
    return (
      <button
        onClick={() => setIsExpanded(true)}
        className="terminal-card flex items-center gap-2 px-4 py-2 text-[var(--success)] hover:border-[var(--success)]"
      >
        <span className="text-[var(--primary)]">$</span>
        <span className="text-xs">dev</span>
        <span className="cursor-blink"></span>
      </button>
    );
  }

  return (
    <div className="terminal-card overflow-hidden bg-[var(--background)]">
      {/* Terminal header */}
      <div className="flex items-center justify-between border-b border-[var(--border)] bg-[var(--surface)] px-4 py-2">
        <div className="flex items-center gap-2">
          <span className="text-[var(--primary)]">$</span>
          <span className="text-xs text-[var(--success)]">dev console</span>
          {loading && <span className="text-xs text-[var(--warning)]">running...</span>}
        </div>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-1.5 text-xs text-[var(--muted)]">
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
              className="h-3 w-3"
            />
            auto
          </label>
          {autoRefresh && lastRefresh && (
            <span className="text-xs text-[var(--muted)]">
              {lastRefresh.toLocaleTimeString("en-US", { hour12: false })}
            </span>
          )}
          <button
            onClick={() => setIsExpanded(false)}
            className="text-[var(--muted)] hover:text-[var(--foreground)]"
          >
            x
          </button>
        </div>
      </div>

      <div className="p-4">
        {/* Parameters section */}
        <div className="mb-4 space-y-3">
          {/* Target */}
          <div className="rounded border border-[var(--border)] bg-[var(--background-secondary)]/50 p-2">
            <div className="mb-1 text-xs text-[var(--muted)]">target:</div>
            <div className="flex flex-wrap items-center gap-3 text-xs">
              <label className="flex items-center gap-1 text-[var(--muted)]">
                <input
                  type="radio"
                  name="target"
                  checked={targetMode === "single"}
                  onChange={() => setTargetMode("single")}
                  className="h-3 w-3"
                />
                single
              </label>
              <label className="flex items-center gap-1 text-[var(--muted)]">
                <input
                  type="radio"
                  name="target"
                  checked={targetMode === "selected"}
                  onChange={() => { setTargetMode("selected"); if (channels.length === 0) loadChannels(); }}
                  className="h-3 w-3"
                />
                selected
              </label>
              <label className="flex items-center gap-1 text-[var(--muted)]">
                <input
                  type="radio"
                  name="target"
                  checked={targetMode === "all"}
                  onChange={() => setTargetMode("all")}
                  className="h-3 w-3"
                />
                all active
              </label>
              {targetMode === "selected" && (
                <span className="text-[var(--muted)]">{selectedUsernames.length} selected</span>
              )}
            </div>

            {targetMode === "selected" && (
              <div className="mt-2">
                <div className="mb-2 flex items-center gap-2">
                  <input
                    type="text"
                    value={channelSearch}
                    onChange={(e) => setChannelSearch(e.target.value)}
                    className="terminal-input text-sm flex-1"
                    placeholder="search @channel..."
                  />
                  <button onClick={loadChannels} className="terminal-btn text-xs" disabled={loading}>
                    refresh
                  </button>
                  <button
                    onClick={() => setSelectedUsernames(channels.filter((c) => c.is_active).map((c) => c.username))}
                    className="terminal-btn text-xs"
                    disabled={channels.length === 0}
                    title="Select all active channels"
                  >
                    all
                  </button>
                  <button
                    onClick={() => setSelectedUsernames([])}
                    className="terminal-btn text-xs"
                    disabled={selectedUsernames.length === 0}
                    title="Clear selection"
                  >
                    none
                  </button>
                </div>
                <div className="max-h-40 overflow-y-auto rounded border border-[var(--border)] p-2">
                  {channels.length === 0 ? (
                    <div className="py-2 text-center text-xs text-[var(--muted)]">no channels</div>
                  ) : (
                    <div className="space-y-1 font-mono text-xs">
                      {channels
                        .filter((c) => c.username.toLowerCase().includes(channelSearch.toLowerCase().replace("@", "")))
                        .map((c) => {
                          const checked = selectedUsernames.includes(c.username);
                          return (
                            <label key={c.id} className="flex items-center justify-between gap-2 py-0.5">
                              <span className={c.is_active ? "text-[var(--foreground)]" : "text-[var(--muted)] line-through"}>
                                @{c.username}
                              </span>
                              <input
                                type="checkbox"
                                checked={checked}
                                onChange={(e) => {
                                  setSelectedUsernames((prev) => {
                                    if (e.target.checked) return prev.includes(c.username) ? prev : [...prev, c.username];
                                    return prev.filter((u) => u !== c.username);
                                  });
                                }}
                                className="h-3 w-3"
                                disabled={!c.is_active}
                                title={!c.is_active ? "Inactive channel" : "Select channel"}
                              />
                            </label>
                          );
                        })}
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>

          {/* Ingestion params */}
          <div className="rounded border border-[var(--border)] bg-[var(--background-secondary)]/50 p-2">
            <div className="mb-1 text-xs text-[var(--muted)]">ingestion params:</div>
            <div className="flex flex-wrap items-end gap-2">
              <div className="flex-1 min-w-[120px]">
                <label className="mb-1 block text-xs text-[var(--muted)]">
                  {targetMode === "single" ? "channel" : "channels"}
                </label>
                <input
                  type="text"
                  value={targetMode === "single" ? channel : ""}
                  onChange={(e) => setChannel(e.target.value)}
                  className="terminal-input text-sm"
                  placeholder={
                    targetMode === "single"
                      ? "@channel"
                      : targetMode === "selected"
                        ? `selected (${selectedUsernames.length || 0})`
                        : `all active (${channels.filter((c) => c.is_active).length})`
                  }
                  disabled={targetMode !== "single"}
                  title={targetMode === "single" ? "Used in target=single" : "Select target=single to use this field"}
                />
              </div>
              <div className="w-28">
                <label className="mb-1 block text-xs text-[var(--muted)]">mode</label>
                <select
                  value={ingestionMode}
                  onChange={(e) => setIngestionMode(e.target.value as "window" | "incremental" | "refresh_recent")}
                  className="terminal-select text-sm w-full"
                  title={
                    ingestionMode === "window"
                      ? "window: fetch last N days (backfill / initial load)"
                      : ingestionMode === "incremental"
                        ? "incremental: fetch only new posts since last fetch (with grace)"
                        : "refresh_recent: re-fetch recent window to update metrics"
                  }
                >
                  <option value="window">window</option>
                  <option value="incremental">incremental</option>
                  <option value="refresh_recent">refresh</option>
                </select>
              </div>
              <div className="w-20">
                <label className="mb-1 block text-xs text-[var(--muted)]">days</label>
                <select
                  value={sinceDays}
                  onChange={(e) => setSinceDays(parseInt(e.target.value) || 7)}
                  className="terminal-select text-sm w-full"
                  title={
                    ingestionMode === "window"
                      ? "window days (since_days)"
                      : "Used for window mode (incremental/refresh ignore this)"
                  }
                >
                  <option value="1">1</option>
                  <option value="3">3</option>
                  <option value="7">7</option>
                  <option value="14">14</option>
                  <option value="30">30</option>
                </select>
              </div>
              <div className="w-24">
                <label className="mb-1 block text-xs text-[var(--muted)]">limit</label>
                <input
                  type="number"
                  value={messageLimit ?? ""}
                  onChange={(e) => setMessageLimit(e.target.value === "" ? null : parseInt(e.target.value))}
                  min={1}
                  max={5000}
                  className="terminal-input text-sm"
                  placeholder="∞"
                  title="Max messages per channel (optional)"
                />
              </div>
            </div>
            <div className="mt-2 text-xs text-[var(--muted)]">
              target controls which channels are affected • use <span className="text-[var(--foreground)]">sync</span> to run ingestion now
            </div>
          </div>

          {/* Collector settings display */}
          {(graceMins !== null || refreshHours !== null) && (
            <div className="text-xs text-[var(--muted)] flex gap-3">
              {graceMins !== null && <span>grace: {graceMins}m</span>}
              {refreshHours !== null && <span>refresh: {refreshHours}h</span>}
            </div>
          )}

          {/* Shared params */}
            <div className="flex flex-wrap items-end gap-3">
              <div className="w-20">
                <label className="mb-1 block text-xs text-[var(--muted)]">novelty h</label>
                <select
                  value={noveltyHours}
                  onChange={(e) => setNoveltyHours(parseInt(e.target.value) || 48)}
                  className="terminal-select text-sm w-full"
                  title="Hours window for novelty scoring (only posts within this window get a novelty badge)"
                >
                  <option value="24">24</option>
                  <option value="48">48</option>
                  <option value="72">72</option>
                  <option value="168">168</option>
                  <option value="720">720</option>
                </select>
              </div>
              <div className="w-24">
                <label className="mb-1 block text-xs text-[var(--muted)]">novelty ctx</label>
                <input
                type="number"
                value={noveltyContextDays}
                onChange={(e) => setNoveltyContextDays(parseInt(e.target.value) || 14)}
                min={1}
                max={90}
                className="terminal-input text-sm"
                title="Days of posts to analyze for novelty scoring"
                />
              </div>
              {noveltyHours > 168 && (
                <label className="flex items-center gap-1 text-xs text-[var(--muted)]" title="Required to run novelty > 168h (can be expensive)">
                  <input
                    type="checkbox"
                    checked={noveltyAllowLargeBackfill}
                    onChange={(e) => setNoveltyAllowLargeBackfill(e.target.checked)}
                    className="h-3 w-3"
                  />
                  confirm 30d
                </label>
              )}
              <div className="w-20">
                <label className="mb-1 block text-xs text-[var(--muted)]">rank</label>
                <select
                  value={rankPeriod}
                  onChange={(e) => setRankPeriod(e.target.value as "daily" | "weekly" | "monthly")}
                  className="terminal-select text-sm w-full"
                  title="Ranking period for the rank action"
                >
                  <option value="daily">1d</option>
                  <option value="weekly">7d</option>
                  <option value="monthly">30d</option>
                </select>
              </div>
              <div className="w-20">
                <label className="mb-1 block text-xs text-[var(--muted)]">pipeline</label>
                <select
                  value={pipelinePeriod}
                  onChange={(e) => setPipelinePeriod(e.target.value as "daily" | "weekly" | "monthly")}
                  className="terminal-select text-sm w-full"
                  title="Pipeline period (fetch window + scoring period)"
                >
                  <option value="daily">1d</option>
                  <option value="weekly">7d</option>
                  <option value="monthly">30d</option>
                </select>
              </div>
              <div className="w-16">
                <label className="mb-1 block text-xs text-[var(--muted)]">formula</label>
                <select
                  value={rankFormula}
                onChange={(e) => setRankFormula(e.target.value)}
                className="terminal-select text-sm w-full"
              >
                <option value="v4">v4</option>
                <option value="v3">v3</option>
              </select>
            </div>
          </div>
        </div>

        {/* OpenRouter warning */}
        {openrouterConfigured === false && (
          <div className="mb-4 rounded border border-[var(--warning)] bg-[var(--warning)]/10 p-2 text-xs text-[var(--warning)]">
            ⚠️ OPENROUTER_API_KEY not configured — novelty scoring disabled
          </div>
        )}

        {/* Action buttons */}
        <div className="mb-4 space-y-2">
          {/* Primary actions */}
          <div className="flex flex-wrap gap-2">
            <button
              onClick={handleAddAndCollect}
              disabled={
                loading ||
                (targetMode === "single" && !sanitizeChannel(channel)) ||
                (targetMode === "selected" && selectedUsernames.length === 0)
              }
              className="terminal-btn text-xs"
              title="Sync (fetch+upsert) using ingestion params for selected target"
            >
              sync
            </button>
            <button onClick={handleRank} disabled={loading} className="terminal-btn text-xs" title={`Rank ${rankPeriod} with ${rankFormula}`}>
              rank
            </button>
            <button onClick={handleNovelty} disabled={loading || openrouterConfigured === false} className="terminal-btn text-xs" title="Compute novelty for selected target (window = novelty h)">
              novelty{noveltyForce ? "!" : ""}
            </button>
            <label className="flex items-center gap-1 text-xs text-[var(--muted)]" title="Force re-analyze posts that already have scores">
              <input
                type="checkbox"
                checked={noveltyForce}
                onChange={(e) => setNoveltyForce(e.target.checked)}
                className="h-3 w-3"
              />
              force
            </label>
            <button onClick={handlePipeline} disabled={loading} className="terminal-btn terminal-btn-primary text-xs" title={`Pipeline for ${pipelinePeriod} + novelty`}>
              pipeline
            </button>
          </div>

          {/* Secondary actions */}
          <div className="flex flex-wrap gap-2 pt-1 border-t border-[var(--border)]">
            <button onClick={() => setShowBulkImport(!showBulkImport)} className="terminal-btn text-xs">
              {showBulkImport ? "hide bulk" : "bulk"}
            </button>
            <button onClick={() => setShowHelp(!showHelp)} className="terminal-btn text-xs">
              {showHelp ? "hide help" : "help"}
            </button>
            <button onClick={() => { setShowChannels(!showChannels); if (!showChannels) loadChannels(); }} className="terminal-btn text-xs">
              {showChannels ? "hide ch" : "channels"}
            </button>
            <button onClick={() => { setShowSettings(!showSettings); if (!showSettings) loadSettings(); }} className="terminal-btn text-xs">
              {showSettings ? "hide cfg" : "config"}
            </button>
            <button onClick={() => { setShowProfiling(!showProfiling); if (!showProfiling) loadProfiling(); }} className="terminal-btn text-xs">
              {showProfiling ? "hide perf" : "perf"}
            </button>
          </div>
        </div>

        {/* Help section */}
        {showHelp && (
          <div className="mb-4 rounded border border-[var(--border)] bg-[var(--background-secondary)] p-3 text-xs text-[var(--muted)]">
            <div className="mb-2 text-[var(--foreground)]">ingestion help</div>
            <div className="space-y-1">
              <div><span className="text-[var(--foreground)]">window</span>: fetch last <span className="text-[var(--foreground)]">days</span> (initial load / backfill), heavy.</div>
              <div><span className="text-[var(--foreground)]">incremental</span>: fetch only new posts since last fetch (uses grace: {graceMins ?? "?"}m).</div>
              <div><span className="text-[var(--foreground)]">refresh</span>: re-fetch recent window to update metrics (uses refresh: {refreshHours ?? "?"}h).</div>
              <div><span className="text-[var(--foreground)]">limit</span>: optional max messages per channel for this run.</div>
              <div className="pt-2">Targets:</div>
              <div>• choose <span className="text-[var(--foreground)]">target</span>: single / selected / all active.</div>
              <div>• <span className="text-[var(--foreground)]">sync</span> runs ingestion for the chosen target.</div>
              <div>• <span className="text-[var(--foreground)]">bulk</span> is for adding/running a pasted list (optionally with auto-rank).</div>
              <div className="pt-2">Novelty:</div>
              <div>• novelty badge appears only if <span className="text-[var(--foreground)]">novelty_score</span> exists (computed for last <span className="text-[var(--foreground)]">{noveltyHours}h</span>).</div>
              <div>• 30d backfill requires explicit confirm and can be expensive.</div>
              <div className="pt-2">Automation:</div>
              <div>• periodic ingestion/novelty/daily v4 are driven by <span className="text-[var(--foreground)]">automation.*</span> settings (see <span className="text-[var(--foreground)]">config</span>).</div>
            </div>
          </div>
        )}

        {/* Bulk import section */}
        {showBulkImport && (
          <div className="mb-4 rounded border border-[var(--border)] bg-[var(--background-secondary)] p-3">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-xs text-[var(--muted)]">bulk ingest (list)</span>
              <input ref={fileInputRef} type="file" accept=".txt" onChange={handleFileUpload} className="hidden" />
              <button onClick={() => fileInputRef.current?.click()} className="terminal-btn px-2 py-1 text-xs">
                load .txt
              </button>
            </div>
            <textarea
              value={bulkChannels}
              onChange={(e) => setBulkChannels(e.target.value)}
              placeholder="@channel1&#10;@channel2"
              className="terminal-input mb-2 w-full font-mono text-xs"
              rows={4}
            />
            <div className="mb-2 flex items-center justify-between">
              <span className="text-xs text-[var(--muted)]">
                {bulkChannels.split(/[\n,]+/).filter((l) => l.trim()).length} channels
              </span>
              <label className="flex items-center gap-1 text-xs text-[var(--muted)]" title="Run ranking after bulk ingest">
                <input
                  type="checkbox"
                  checked={bulkAutoRank}
                  onChange={(e) => setBulkAutoRank(e.target.checked)}
                  className="h-3 w-3"
                />
                auto rank
              </label>
            </div>
            <div className="flex items-center justify-end">
              <button onClick={handleBulkImport} disabled={loading || !bulkChannels.trim()} className="terminal-btn terminal-btn-primary text-xs">
                run bulk
              </button>
            </div>
          </div>
        )}

        {/* Channel list */}
        {showChannels && (
          <div className="mb-4 rounded border border-[var(--border)] bg-[var(--background-secondary)] p-3">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-xs text-[var(--muted)]">channels ({channels.length})</span>
              <button onClick={loadChannels} className="terminal-btn px-2 py-1 text-xs">
                refresh
              </button>
            </div>
            <div className="max-h-48 overflow-y-auto">
              {channels.length === 0 ? (
                <div className="py-4 text-center text-xs text-[var(--muted)]">no channels</div>
              ) : (
                <div className="space-y-1 font-mono text-xs">
                  {channels.map((ch) => (
                    <div key={ch.id} className="flex items-center justify-between py-1">
                      <span className={ch.is_active ? "text-[var(--success)]" : "text-[var(--muted)] line-through"}>
                        @{ch.username}
                      </span>
                      <div className="flex items-center gap-2">
                        <span className="text-[var(--muted)]">{ch.posts_count}</span>
                        <button
                          onClick={() => handleToggleChannel(ch.id, ch.is_active)}
                          className={`px-1.5 py-0.5 ${ch.is_active ? "text-[var(--success)]" : "text-[var(--muted)]"}`}
                        >
                          {ch.is_active ? "on" : "off"}
                        </button>
                        <button
                          onClick={() => handleDeleteChannel(ch.id, ch.username)}
                          className="text-[var(--danger)]"
                        >
                          del
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}

        {/* Settings section */}
        {showSettings && (
          <div className="mb-4 rounded border border-[var(--border)] bg-[var(--background-secondary)] p-3">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-xs text-[var(--muted)]">settings</span>
              <button onClick={loadSettings} disabled={settingsLoading} className="terminal-btn px-2 py-1 text-xs">
                {settingsLoading ? "..." : "refresh"}
              </button>
            </div>
            {Object.keys(settings).length === 0 ? (
              <div className="py-4 text-center text-xs text-[var(--muted)]">loading...</div>
            ) : (
              <div className="space-y-3 font-mono text-xs">
                {/* General settings (non-weight) */}
                <div className="space-y-2">
                  {Object.entries(settings)
                    .filter(([key]) => !key.startsWith("novelty.weight."))
                    .sort(([a], [b]) => a.localeCompare(b))
                    .map(([key, value]) => (
                      <div key={key} className="flex items-center justify-between gap-2">
                        <span className="text-[var(--muted)] truncate" title={key}>
                          {key.replace("ranking.", "").replace("collector.", "").replace("novelty.", "")}
                        </span>
                        <input
                          type="number"
                          value={typeof value === "number" ? value : 0}
                          onChange={(e) => {
                            const newVal = key.includes("weight") || key.includes("per_day")
                              ? parseFloat(e.target.value)
                              : parseInt(e.target.value);
                            handleUpdateSetting(key, newVal);
                          }}
                          className="terminal-input w-24 text-right text-xs"
                          step={key.includes("weight") || key.includes("per_day") ? 0.1 : 1}
                        />
                      </div>
                    ))}
                </div>

                {/* Essence criteria weights */}
                <details className="group">
                  <summary className="cursor-pointer text-[var(--primary)] hover:text-[var(--accent)]">
                    essence weights (10 criteria)
                  </summary>
                  <div className="mt-2 space-y-1 pl-2 border-l border-[var(--border)]">
                    {Object.entries(settings)
                      .filter(([key]) => key.startsWith("novelty.weight."))
                      .sort(([a], [b]) => a.localeCompare(b))
                      .map(([key, value]) => {
                        const criterion = key.replace("novelty.weight.", "");
                        return (
                          <div key={key} className="flex items-center justify-between gap-2">
                            <span className="text-[var(--muted)]" title={key}>
                              {criterion}
                            </span>
                            <input
                              type="number"
                              value={typeof value === "number" ? value : 1}
                              onChange={(e) => handleUpdateSetting(key, parseFloat(e.target.value))}
                              className="terminal-input w-16 text-right text-xs"
                              step={0.5}
                              min={0}
                              max={10}
                            />
                          </div>
                        );
                      })}
                  </div>
                </details>
              </div>
            )}
          </div>
        )}

        {/* Profiling section */}
        {showProfiling && (
          <div className="mb-4 rounded border border-[var(--border)] bg-[var(--background-secondary)] p-3">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-xs text-[var(--muted)]">profiling (7d) — {profilingTotalRuns} runs</span>
              <button onClick={loadProfiling} className="terminal-btn px-2 py-1 text-xs">
                refresh
              </button>
            </div>
            {Object.keys(profilingStats).length === 0 ? (
              <div className="py-4 text-center text-xs text-[var(--muted)]">no data</div>
            ) : (
              <div className="space-y-1 font-mono text-xs">
                {Object.entries(profilingStats).map(([task, stats]) => (
                  <div key={task} className="flex items-center justify-between py-1">
                    <span className="text-[var(--foreground)] truncate" title={task}>
                      {task.replace("_", " ")}
                    </span>
                    <div className="flex items-center gap-3 text-[var(--muted)]">
                      <span title="count">{stats.count}×</span>
                      <span title="avg duration">{Math.round(stats.avg_duration_ms)}ms</span>
                      {stats.success_rate !== undefined && (
                        <span
                          className={stats.success_rate >= 95 ? "text-[var(--success)]" : stats.success_rate >= 80 ? "text-[var(--warning)]" : "text-[var(--danger)]"}
                          title="success rate"
                        >
                          {stats.success_rate}%
                        </span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Terminal log output */}
        <div className="rounded border border-[var(--border)] bg-[#0d0d0d] p-3">
          <div className="max-h-32 overflow-y-auto font-mono text-xs">
            {logs.length === 0 ? (
              <div className="text-[var(--muted)]">
                <span className="text-[var(--success)]">tpe</span>
                <span className="text-[var(--muted)]">:</span>
                <span className="text-[var(--primary)]">~</span>
                <span className="text-[var(--muted)]">$ </span>
                <span className="cursor-blink"></span>
              </div>
            ) : (
              logs.map((log, i) => (
                <div key={i} className="flex gap-2">
                  <span className="text-[var(--muted)]">[{log.time}]</span>
                  <span
                    className={
                      log.type === "success"
                        ? "text-[var(--success)]"
                        : log.type === "error"
                        ? "text-[var(--danger)]"
                        : log.type === "pending"
                        ? "text-[var(--warning)]"
                        : "text-[var(--primary)]"
                    }
                  >
                    {log.message}
                  </span>
                </div>
              ))
            )}
            <div ref={logEndRef} />
          </div>
        </div>

        {/* Task status */}
        {task && (
          <div className="mt-3 flex items-center gap-2 text-xs">
            <span className="text-[var(--muted)]">status:</span>
            <span
              className={
                task.status === "SUCCESS"
                  ? "text-[var(--success)]"
                  : task.status === "FAILURE"
                  ? "text-[var(--danger)]"
                  : "text-[var(--warning)]"
              }
            >
              {task.status}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}
