export type ListingStatus = "notified" | "dismissed" | "seeded" | "invalid";

export interface Listing {
  listing_id: string;
  user_id: string;
  seen_at: number;
  status: ListingStatus;
  reason: string;
  company_name: string;
  title: string;
  url: string;
  source: string;
  fit_score?: number;
}

export interface ListingsResponse {
  listings: Listing[];
}

export interface CurrentUser {
  user_id: string;
  is_admin: boolean;
  ntfy_topic: string;
  onboarding_completed: boolean;
  active: boolean;
}

/** Mirrors classifier.build_fit_system_prompt so the UI cannot drift from what is actually sent. */
export interface PromptPreview {
  system_preamble: string;
  criteria_label: string;
  resume_label: string;
  has_resume: boolean;
  response_instruction: string;
}

export interface UserConfig {
  fit_prompt?: string;
  companies?: string[];
  job_types?: string[];
  email_to?: string[];
  prompt_preview?: PromptPreview;
}

export interface ConfigOptions {
  companies: string[];
  job_types: string[];
}

export interface ClassifierTestRequest {
  fit_prompt: string;
  company_name: string;
  title: string;
  locations: string;
  description: string;
}

export interface ClassifierTestResult {
  fits: boolean;
  reason: string;
  fit_score: number | null;
}

export interface LoginTokens {
  access_token: string;
  expires_in: number;
  refresh_token?: string;
}

export interface NewPasswordChallenge {
  challenge: "NEW_PASSWORD_REQUIRED";
  session: string;
}

export type LoginResponse = LoginTokens | NewPasswordChallenge;

export function isNewPasswordChallenge(response: LoginResponse): response is NewPasswordChallenge {
  return "challenge" in response && response.challenge === "NEW_PASSWORD_REQUIRED";
}

export interface TimeSeriesValuePoint {
  timestamp: string;
  value: number;
}

export interface ThroughputPoint {
  timestamp: string;
  users: number;
  new: number;
  notified: number;
  dismissed: number;
}

export interface BacklogPoint {
  timestamp: string;
  count: number;
}

export interface TokenUsagePoint {
  timestamp: string;
  input_tokens: number;
  output_tokens: number;
}

export interface Metrics {
  invocations: number;
  errors: number | null;
  avg_duration_ms: number | null;
  last_ran: string | null;
  duration_series: TimeSeriesValuePoint[];
  throughput_series: ThroughputPoint[];
  backlog_series: BacklogPoint[];
  token_usage_series: TokenUsagePoint[];
}

export interface LogEvent {
  timestamp: string;
  message: string;
  is_failure: boolean;
}

export interface LogsResponse {
  events: LogEvent[];
}

export interface AdminUser {
  user_id: string;
  email?: string;
  is_admin?: boolean;
  ntfy_topic?: string;
  active?: boolean;
  created_at?: number;
  onboarding_completed?: boolean;
  query_count?: number;
}

export interface Company {
  company_name: string;
  source_kind: string;
  added_by?: string;
  created_at?: number;
  board_token?: string;
  board_name?: string;
  intern_url?: string;
  newgrad_url?: string;
  fulltime_url?: string;
  general_url?: string;
}

export interface SourceHealth {
  source_name: string;
  last_success_at?: number;
  last_failure_at?: number;
  success_count?: number;
  failure_count?: number;
  consecutive_failures?: number;
  alerted?: boolean;
}

export interface TokenUsageByUser {
  user_id: string;
  input_tokens: number;
  output_tokens: number;
}

export interface UserNotification {
  company_name: string;
  title: string;
  url: string;
  seen_at: number;
  fit_score?: number | null;
}

export interface NotificationsByUser {
  user_id: string;
  notifications: UserNotification[];
}

export interface AdminActivity {
  token_usage_by_user: TokenUsageByUser[];
  notifications_by_user: NotificationsByUser[];
}

export interface UserProfile {
  resume_filename?: string;
  resume_text?: string;
  resume_url?: string;
  resume_uploaded_at?: number;
  resume_fetch_error?: string;
}

export interface NewCompanyRequest {
  company_name: string;
  source_kind: string;
  board_token: string;
  board_name: string;
  intern_url: string;
  newgrad_url: string;
  fulltime_url: string;
}
