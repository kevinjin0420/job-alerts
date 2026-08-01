import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import { apiRequest } from "./client";
import type {
  AdminActivity,
  AdminUser,
  ClassifierTestRequest,
  ClassifierTestResult,
  Company,
  ConfigOptions,
  CurrentUser,
  ListingsResponse,
  LogsResponse,
  Metrics,
  NewCompanyRequest,
  SourceHealth,
  UserConfig,
  UserProfile,
} from "./types";

const AUTO_REFRESH_MS = 60_000;

export const queryKeys = {
  me: ["me"] as const,
  listings: (range?: string) => ["listings", range ?? "all"] as const,
  config: ["config"] as const,
  options: ["options"] as const,
  profile: ["profile"] as const,
  metrics: (range: string) => ["metrics", range] as const,
  logs: ["logs"] as const,
  adminUsers: ["admin", "users"] as const,
  adminSettings: ["admin", "settings"] as const,
  adminCompanies: ["admin", "companies"] as const,
  adminSourceHealth: ["admin", "source-health"] as const,
  adminActivity: (range: string) => ["admin", "activity", range] as const,
};

export function useCurrentUser(): UseQueryResult<CurrentUser, Error> {
  return useQuery({
    queryKey: queryKeys.me,
    queryFn: () => apiRequest<CurrentUser>("/api/me"),
    staleTime: 5 * 60 * 1000,
  });
}

export function useListings(range?: string): UseQueryResult<ListingsResponse, Error> {
  return useQuery({
    queryKey: queryKeys.listings(range),
    queryFn: () =>
      apiRequest<ListingsResponse>(range ? `/api/listings?range=${encodeURIComponent(range)}` : "/api/listings"),
  });
}

export function useRetryListing(): UseMutationResult<void, Error, string> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (listingId: string) =>
      apiRequest<void>(`/api/listings/${encodeURIComponent(listingId)}`, { method: "DELETE" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["listings"] }),
  });
}

export function useUserConfig(): UseQueryResult<UserConfig, Error> {
  return useQuery({
    queryKey: queryKeys.config,
    queryFn: () => apiRequest<UserConfig>("/api/config"),
  });
}

export function useConfigOptions(): UseQueryResult<ConfigOptions, Error> {
  return useQuery({
    queryKey: queryKeys.options,
    queryFn: () => apiRequest<ConfigOptions>("/api/options"),
    staleTime: 10 * 60 * 1000,
  });
}

/** The backend merges onto the stored item, so a partial patch is intentional. */
export function useSaveConfig(): UseMutationResult<void, Error, UserConfig> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (config: UserConfig) => apiRequest<void>("/api/config", { method: "PUT", body: config }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.config }),
  });
}

export function useTestClassifier(): UseMutationResult<ClassifierTestResult, Error, ClassifierTestRequest> {
  return useMutation({
    mutationFn: (request: ClassifierTestRequest) =>
      apiRequest<ClassifierTestResult>("/api/test-classifier", { method: "POST", body: request }),
  });
}

export function useMetrics(range: string): UseQueryResult<Metrics, Error> {
  return useQuery({
    queryKey: queryKeys.metrics(range),
    queryFn: () => apiRequest<Metrics>(`/api/metrics?range=${encodeURIComponent(range)}`),
    refetchInterval: AUTO_REFRESH_MS,
  });
}

export function useLogs(): UseQueryResult<LogsResponse, Error> {
  return useQuery({
    queryKey: queryKeys.logs,
    queryFn: () => apiRequest<LogsResponse>("/api/logs"),
    refetchInterval: AUTO_REFRESH_MS,
  });
}

export function useAdminActivity(range: string): UseQueryResult<AdminActivity, Error> {
  return useQuery({
    queryKey: queryKeys.adminActivity(range),
    queryFn: () => apiRequest<AdminActivity>(`/api/admin/activity?range=${encodeURIComponent(range)}`),
    refetchInterval: AUTO_REFRESH_MS,
  });
}

export function useAdminUsers(): UseQueryResult<{ users: AdminUser[] }, Error> {
  return useQuery({
    queryKey: queryKeys.adminUsers,
    queryFn: () => apiRequest<{ users: AdminUser[] }>("/api/admin/users"),
  });
}

export function useInviteUser(): UseMutationResult<{ status: string; ntfy_topic: string }, Error, string> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (email: string) =>
      apiRequest<{ status: string; ntfy_topic: string }>("/api/admin/users", { method: "POST", body: { email } }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.adminUsers }),
  });
}

export function useRemoveUser(): UseMutationResult<void, Error, string> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (userId: string) =>
      apiRequest<void>(`/api/admin/users/${encodeURIComponent(userId)}`, { method: "DELETE" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.adminUsers }),
  });
}

export function useAdminSettings(): UseQueryResult<{ classifier_model: string }, Error> {
  return useQuery({
    queryKey: queryKeys.adminSettings,
    queryFn: () => apiRequest<{ classifier_model: string }>("/api/admin/settings"),
  });
}

export function useSaveClassifierModel(): UseMutationResult<void, Error, string> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (classifierModel: string) =>
      apiRequest<void>("/api/admin/settings", { method: "PUT", body: { classifier_model: classifierModel } }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.adminSettings }),
  });
}

export function useTriggerScan(): UseMutationResult<{ status: string }, Error, void> {
  return useMutation({
    mutationFn: () => apiRequest<{ status: string }>("/api/admin/trigger-scan", { method: "POST" }),
  });
}

export function useAdminCompanies(): UseQueryResult<{ companies: Company[] }, Error> {
  return useQuery({
    queryKey: queryKeys.adminCompanies,
    queryFn: () => apiRequest<{ companies: Company[] }>("/api/admin/companies"),
  });
}

export function useSourceHealth(): UseQueryResult<{ sources: SourceHealth[] }, Error> {
  return useQuery({
    queryKey: queryKeys.adminSourceHealth,
    queryFn: () => apiRequest<{ sources: SourceHealth[] }>("/api/admin/source-health"),
  });
}

export function useAddCompany(): UseMutationResult<void, Error, NewCompanyRequest> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (company: NewCompanyRequest) =>
      apiRequest<void>("/api/admin/companies", { method: "POST", body: company }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.adminCompanies });
      void queryClient.invalidateQueries({ queryKey: queryKeys.options });
    },
  });
}

export function useRemoveCompany(): UseMutationResult<void, Error, string> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (companyName: string) =>
      apiRequest<void>(`/api/admin/companies/${encodeURIComponent(companyName)}`, { method: "DELETE" }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.adminCompanies });
      void queryClient.invalidateQueries({ queryKey: queryKeys.options });
    },
  });
}

export function useProfile(): UseQueryResult<UserProfile, Error> {
  return useQuery({
    queryKey: queryKeys.profile,
    queryFn: () => apiRequest<UserProfile>("/api/profile"),
  });
}

export function useUploadResume(): UseMutationResult<
  UserProfile,
  Error,
  { filename: string; content_base64: string }
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body) => apiRequest<UserProfile>("/api/profile/resume", { method: "POST", body }),
    onSuccess: (profile) => {
      queryClient.setQueryData(queryKeys.profile, profile);
      void queryClient.invalidateQueries({ queryKey: queryKeys.config });
    },
  });
}

export function useSaveResumeUrl(): UseMutationResult<UserProfile, Error, string> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (url: string) => apiRequest<UserProfile>("/api/profile/resume-url", { method: "POST", body: { url } }),
    onSuccess: (profile) => {
      queryClient.setQueryData(queryKeys.profile, profile);
      void queryClient.invalidateQueries({ queryKey: queryKeys.config });
    },
  });
}

export function useRemoveResume(): UseMutationResult<void, Error, void> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiRequest<void>("/api/profile/resume", { method: "DELETE" }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.profile });
      void queryClient.invalidateQueries({ queryKey: queryKeys.config });
    },
  });
}

export function useSaveNtfyTopic(): UseMutationResult<void, Error, string> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (ntfyTopic: string) => apiRequest<void>("/api/me", { method: "PUT", body: { ntfy_topic: ntfyTopic } }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.me }),
  });
}

export function useTestNotification(): UseMutationResult<{ status: string }, Error, string> {
  return useMutation({
    mutationFn: (ntfyTopic: string) =>
      apiRequest<{ status: string }>("/api/me/test-notification", { method: "POST", body: { ntfy_topic: ntfyTopic } }),
  });
}

export function useGenerateApiKey(): UseMutationResult<{ api_key: string }, Error, void> {
  return useMutation({
    mutationFn: () => apiRequest<{ api_key: string }>("/api/apikey", { method: "POST" }),
  });
}

export function useSetSubscription(): UseMutationResult<void, Error, boolean> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (active: boolean) =>
      apiRequest<void>(active ? "/api/me/resubscribe" : "/api/me/unsubscribe", { method: "POST" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.me }),
  });
}

export function useDeleteAccount(): UseMutationResult<void, Error, void> {
  return useMutation({
    mutationFn: () => apiRequest<void>("/api/me", { method: "DELETE" }),
  });
}

export function useCompleteOnboarding(): UseMutationResult<void, Error, void> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiRequest<void>("/api/onboarding/complete", { method: "POST" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.me }),
  });
}
