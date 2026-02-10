import type {
  FeedParams,
  FeedResponse,
  Stats,
  Summary,
  TokenResponse,
  TelegramAuthData,
  User,
  VoteRequest,
  VoteResponse,
  VoteStats,
  ApiError,
  CollectRequest,
  CollectResponse,
  AddChannelRequest,
  AddChannelResponse,
  TaskStatus,
  BulkImportRequest,
  BulkImportResponse,
  IngestRequest,
  IngestResponse,
  ChannelInfo,
  SearchParams,
  SearchResponse,
} from "@/types";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

class ApiClient {
  private baseUrl: string;
  private token: string | null = null;

  constructor(baseUrl: string = API_BASE_URL) {
    this.baseUrl = baseUrl;
    // Load token from localStorage on client side
    if (typeof window !== "undefined") {
      this.token = localStorage.getItem("auth_token");
    }
  }

  setToken(token: string | null) {
    this.token = token;
    if (typeof window !== "undefined") {
      if (token) {
        localStorage.setItem("auth_token", token);
      } else {
        localStorage.removeItem("auth_token");
      }
    }
  }

  getToken(): string | null {
    return this.token;
  }

  private async request<T>(
    endpoint: string,
    options: RequestInit = {}
  ): Promise<T> {
    const url = `${this.baseUrl}${endpoint}`;
    const headers: HeadersInit = {
      "Content-Type": "application/json",
      ...options.headers,
    };

    if (this.token) {
      (headers as Record<string, string>)["Authorization"] = `Bearer ${this.token}`;
    }

    const response = await fetch(url, {
      ...options,
      headers,
    });

    if (!response.ok) {
      const error: ApiError = await response.json().catch(() => ({
        detail: `HTTP ${response.status}: ${response.statusText}`,
      }));
      throw new Error(error.detail);
    }

    return response.json();
  }

  // === Health ===

  async health(): Promise<{ status: string }> {
    return this.request("/health");
  }

  // === Stats ===

  async getStats(period?: string): Promise<Stats> {
    const query = period ? `?period=${encodeURIComponent(period)}` : "";
    return this.request(`/stats${query}`);
  }

  // === Feed ===

  async getFeed(params: FeedParams = {}): Promise<FeedResponse> {
    const searchParams = new URLSearchParams();
    if (params.period) searchParams.set("period", params.period);
    if (params.limit) searchParams.set("limit", params.limit.toString());
    if (params.offset) searchParams.set("offset", params.offset.toString());
    if (params.formula) searchParams.set("formula", params.formula);
    if (params.channel) searchParams.set("channel", params.channel);
    if (params.min_views !== undefined) searchParams.set("min_views", params.min_views.toString());
    if (params.min_replies !== undefined) searchParams.set("min_replies", params.min_replies.toString());
    if (params.min_reactions !== undefined) searchParams.set("min_reactions", params.min_reactions.toString());
    if (params.min_forwards !== undefined) searchParams.set("min_forwards", params.min_forwards.toString());
    if (params.min_novelty !== undefined) searchParams.set("min_novelty", params.min_novelty.toString());
    if (params.sort_by) searchParams.set("sort_by", params.sort_by);
    if (params.sort_dir) searchParams.set("sort_dir", params.sort_dir);

    const query = searchParams.toString();
    return this.request(`/feed${query ? `?${query}` : ""}`);
  }

  // === Search ===

  async search(params: SearchParams): Promise<SearchResponse> {
    const searchParams = new URLSearchParams();
    searchParams.set("q", params.q);
    if (params.mode) searchParams.set("mode", params.mode);
    if (params.limit) searchParams.set("limit", params.limit.toString());
    if (params.offset) searchParams.set("offset", params.offset.toString());
    if (params.channel) searchParams.set("channel", params.channel);
    if (params.min_views !== undefined) searchParams.set("min_views", params.min_views.toString());
    if (params.min_replies !== undefined) searchParams.set("min_replies", params.min_replies.toString());
    if (params.min_reactions !== undefined) searchParams.set("min_reactions", params.min_reactions.toString());
    if (params.min_forwards !== undefined) searchParams.set("min_forwards", params.min_forwards.toString());
    if (params.since) searchParams.set("since", params.since);
    if (params.until) searchParams.set("until", params.until);
    return this.request(`/search?${searchParams.toString()}`);
  }

  // === Auth ===

  async authTelegram(data: TelegramAuthData): Promise<TokenResponse> {
    const response = await this.request<TokenResponse>("/auth/telegram", {
      method: "POST",
      body: JSON.stringify(data),
    });
    this.setToken(response.access_token);
    return response;
  }

  async devLogin(username: string = "test_user"): Promise<TokenResponse> {
    const response = await this.request<TokenResponse>(
      `/auth/dev-login?username=${encodeURIComponent(username)}`,
      { method: "POST" }
    );
    this.setToken(response.access_token);
    return response;
  }

  async getMe(): Promise<User> {
    return this.request("/auth/me");
  }

  logout() {
    this.setToken(null);
  }

  // === Vote ===

  async vote(request: VoteRequest): Promise<VoteResponse> {
    return this.request("/vote", {
      method: "POST",
      body: JSON.stringify(request),
    });
  }

  async getVoteStats(postId: number): Promise<VoteStats> {
    return this.request(`/vote/${postId}`);
  }

  // === Summary ===

  async getSummary(period?: string): Promise<Summary> {
    const query = period ? `?period=${encodeURIComponent(period)}` : "";
    return this.request(`/summary${query}`);
  }

  // === Admin (dev mode) ===

  async addChannel(request: AddChannelRequest): Promise<AddChannelResponse> {
    return this.request("/admin/channel", {
      method: "POST",
      body: JSON.stringify(request),
    });
  }

  async triggerCollect(request: CollectRequest = {}): Promise<CollectResponse> {
    return this.request("/admin/collect", {
      method: "POST",
      body: JSON.stringify(request),
    });
  }

  async bulkImport(request: BulkImportRequest): Promise<BulkImportResponse> {
    return this.request("/admin/import", {
      method: "POST",
      body: JSON.stringify(request),
    });
  }

  async ingestChannels(request: IngestRequest): Promise<IngestResponse> {
    return this.request("/admin/ingest", {
      method: "POST",
      body: JSON.stringify(request),
    });
  }

  async getTaskStatus(taskId: string): Promise<TaskStatus> {
    return this.request(`/admin/task/${taskId}`);
  }

  async listChannels(): Promise<ChannelInfo[]> {
    return this.request("/admin/channels");
  }

  async toggleChannel(
    channelId: number,
    isActive: boolean
  ): Promise<{ status: string; channel_id: number; is_active: boolean }> {
    return this.request(`/admin/channel/${channelId}?is_active=${isActive}`, {
      method: "PATCH",
    });
  }

  async deleteChannel(
    channelId: number
  ): Promise<{ status: string; channel_id: number; username: string }> {
    return this.request(`/admin/channel/${channelId}`, {
      method: "DELETE",
    });
  }

  async updateChannelStats(
    days: number = 30
  ): Promise<{ status: string; task_id: string; days: number }> {
    return this.request(`/admin/channel-stats?days=${days}`, {
      method: "POST",
    });
  }

  async triggerPipeline(params: {
    since_days?: number;
    with_novelty?: boolean;
    novelty_limit?: number;
    novelty_analysis_hours?: number;
    novelty_context_days?: number;
    allow_large_novelty_backfill?: boolean;
    rank_periods?: Array<"daily" | "weekly" | "monthly">;
    fetch_mode?: "window" | "incremental" | "refresh_recent";
    channels?: string[];
  } = {}): Promise<{
    status: string;
    pipeline_id: string;
    with_novelty: boolean;
    message: string;
  }> {
    return this.request("/admin/pipeline", {
      method: "POST",
      body: JSON.stringify({
        since_days: params.since_days ?? 1,
        with_novelty: params.with_novelty ?? true,
        novelty_limit: params.novelty_limit ?? 50,
        novelty_analysis_hours: params.novelty_analysis_hours ?? 48,
        novelty_context_days: params.novelty_context_days ?? 14,
        allow_large_novelty_backfill: params.allow_large_novelty_backfill ?? false,
        rank_periods: params.rank_periods ?? ["daily"],
        fetch_mode: params.fetch_mode ?? "window",
        channels: params.channels ?? null,
      }),
    });
  }

  async getAdminConfig(): Promise<{
    openrouter_configured: boolean;
    telegram_configured: boolean;
  }> {
    return this.request("/admin/config");
  }

  async triggerEmbeddingsBackfill(params: {
    batch_size?: number;
    limit?: number;
    force?: boolean;
  } = {}): Promise<{ status: string; task_id: string }> {
    const searchParams = new URLSearchParams();
    if (params.batch_size) searchParams.set("batch_size", params.batch_size.toString());
    if (params.limit) searchParams.set("limit", params.limit.toString());
    if (params.force) searchParams.set("force", "true");
    return this.request(`/admin/embeddings/backfill?${searchParams.toString()}`, {
      method: "POST",
    });
  }

  async getEmbeddingsStatus(): Promise<{
    eligible_posts: number;
    embedded_posts: number;
    coverage_pct: number;
    missing: number;
  }> {
    return this.request("/admin/embeddings/status");
  }

  async triggerNovelty(params: {
    limit?: number;
    analysisHours?: number;
    contextDays?: number;
    force?: boolean;
    allowLargeBackfill?: boolean;
    channels?: string[];
  } = {}): Promise<{ status: string; task_id: string; analysis_hours: number; force: boolean }> {
    return this.request("/admin/novelty/run", {
      method: "POST",
      body: JSON.stringify({
        limit: params.limit ?? null,
        analysis_hours: params.analysisHours ?? 48,
        context_days: params.contextDays ?? 30,
        force: params.force ?? false,
        allow_large_backfill: params.allowLargeBackfill ?? false,
        channels: params.channels ?? null,
      }),
    });
  }

  async triggerRank(params: {
    period: string;
    formula: string;
  }): Promise<{ status: string; task_id: string; period: string; formula: string }> {
    const searchParams = new URLSearchParams();
    searchParams.set("period", params.period);
    searchParams.set("formula", params.formula);
    return this.request(`/admin/rank?${searchParams.toString()}`, {
      method: "POST",
    });
  }

  // === Settings ===

  async getSettings(): Promise<{
    settings: Record<string, number | string | boolean>;
    defaults: Record<string, number | string | boolean>;
  }> {
    return this.request("/admin/settings");
  }

  async updateSettings(
    settings: Record<string, number | string | boolean>
  ): Promise<{
    updated: string[];
    settings: Record<string, number | string | boolean>;
  }> {
    return this.request("/admin/settings", {
      method: "PUT",
      body: JSON.stringify({ settings }),
    });
  }

  // === Profiling ===

  async getProfilingRuns(
    limit: number = 50,
    taskName?: string
  ): Promise<{
    runs: Array<{
      id: number;
      task_name: string;
      started_at: string | null;
      finished_at: string | null;
      duration_ms: number | null;
      status: string;
      input_params: Record<string, unknown> | null;
      result_summary: Record<string, unknown> | null;
      error_message: string | null;
    }>;
    total: number;
  }> {
    const params = new URLSearchParams({ limit: limit.toString() });
    if (taskName) params.set("task_name", taskName);
    return this.request(`/admin/profiling?${params.toString()}`);
  }

  async getProfilingStats(
    days: number = 7,
    taskName?: string
  ): Promise<{
    by_task: Record<string, {
      count: number;
      avg_duration_ms: number;
      max_duration_ms: number;
      min_duration_ms: number;
      success_rate?: number;
      total_runs?: number;
    }>;
    total_runs: number;
    days: number;
  }> {
    const params = new URLSearchParams({ days: days.toString() });
    if (taskName) params.set("task_name", taskName);
    return this.request(`/admin/profiling/stats?${params.toString()}`);
  }
}

// Singleton instance
export const api = new ApiClient();

// Export class for custom instances
export { ApiClient };
