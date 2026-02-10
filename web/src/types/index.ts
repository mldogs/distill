// Types matching api/schemas.py

// === Auth ===

export interface TelegramAuthData {
  id: number;
  first_name: string;
  last_name?: string;
  username?: string;
  photo_url?: string;
  auth_date: number;
  hash: string;
}

export interface User {
  id: number;
  provider: string;
  username?: string;
  display_name?: string;
  avatar_url?: string;
  is_admin?: boolean;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  user: User;
}

// === Feed ===

export interface Channel {
  id: number;
  username: string;
  name?: string;
}

export interface ScoreExplanation {
  formula: string;
  inputs: Record<string, number>;
  weights?: Record<string, number>;
  components: Record<string, number>;
}

export interface Post {
  id: number;
  text?: string;
  permalink: string;
  posted_at: string;
  views?: number;
  forwards?: number;
  replies?: number;
  reactions_count?: number;
  media_type?: string;
  score: number;
  explanation?: ScoreExplanation;
  novelty_score?: number;
  channel: Channel;
}

export interface FeedResponse {
  posts: Post[];
  total: number;
  period: string;
  formula: string;
}

export type FeedSortBy = "score" | "posted_at" | "views" | "replies" | "reactions" | "forwards" | "novelty";
export type FeedSortDir = "desc" | "asc";

export interface FeedParams {
  period?: string;
  limit?: number;
  offset?: number;
  formula?: string;
  channel?: string;
  min_views?: number;
  min_replies?: number;
  min_reactions?: number;
  min_forwards?: number;
  min_novelty?: number;
  sort_by?: FeedSortBy;
  sort_dir?: FeedSortDir;
}

// === Vote ===

export interface VoteRequest {
  post_id: number;
  value: -1 | 0 | 1;
}

export interface VoteStats {
  total_votes: number;
  vote_sum: number;
  vote_avg: number;
}

export interface VoteResponse {
  success: boolean;
  post_id: number;
  user_vote: number;
  stats: VoteStats;
}

// === Summary ===

export interface Summary {
  id: number;
  period_type: string;
  period_start: string;
  period_end: string;
  title?: string;
  content_markdown: string;
  formula_version: string;
  post_count: number;
  channel_count: number;
}

// === Stats ===

export interface Stats {
  channels_count: number;
  posts_count: number;
  scores_count: number;
  votes_count: number;
  users_count: number;
  avg_score: number;
}

// === Admin ===

export interface CollectRequest {
  channel?: string;
  since_days?: number;
  limit?: number;
  mode?: "window" | "incremental" | "refresh_recent";
}

export interface CollectResponse {
  status: string;
  task_id?: string;
  channels?: string[];
  message: string;
}

export interface BulkImportRequest {
  channels: string[];
  since_days?: number;
  auto_rank?: boolean;
}

export interface BulkImportResponse {
  status: string;
  task_id: string;
  channels_count: number;
  message: string;
}

export interface IngestRequest {
  channels: string[];
  mode?: "window" | "incremental" | "refresh_recent";
  since_days?: number;
  limit?: number;
  auto_rank?: boolean;
}

export interface IngestResponse {
  status: string;
  task_id: string;
  channels_count: number;
  normalized_channels: string[];
  message: string;
}

export interface ChannelInfo {
  id: number;
  username: string;
  name?: string;
  is_active: boolean;
  posts_count: number;
}

export interface AddChannelRequest {
  username: string;
  name?: string;
}

export interface AddChannelResponse {
  status: string;
  channel_id: number;
  username: string;
}

export interface TaskStatus {
  task_id: string;
  status: string;
  result?: Record<string, unknown>;
  error?: string;
}

// === Search ===

export interface SearchResultItem {
  post: Post;
  relevance_score: number;
  match_type: string;
}

export interface SearchResponse {
  results: SearchResultItem[];
  total: number;
  query: string;
  mode: string;
  took_ms?: number;
}

export interface SearchParams {
  q: string;
  mode?: "lexical" | "semantic" | "hybrid";
  limit?: number;
  offset?: number;
  channel?: string;
  min_views?: number;
  min_replies?: number;
  min_reactions?: number;
  min_forwards?: number;
  since?: string;
  until?: string;
}

// === Errors ===

export interface ApiError {
  detail: string;
}
