import type { Company, SourceHealth } from "../api/types";

/** Sources name themselves "{kind}:{company}:{job_type}"; "community" is the one exception. */
export function companyHealthRows(company: Company, health: SourceHealth[]): SourceHealth[] {
  if (company.source_kind === "community") {
    return health.filter((source) => source.source_name === company.source_kind);
  }
  return health.filter((source) => source.source_name.startsWith(`${company.source_kind}:${company.company_name}:`));
}

export function sourceLabel(company: Company): string {
  return company.source_kind === "community"
    ? company.source_kind
    : `${company.source_kind}:${company.company_name}`;
}

export function jobTypesLabel(company: Company): string {
  const present = (["intern_url", "newgrad_url", "fulltime_url"] as const).filter((field) => company[field]);
  return present.map((field) => field.replace("_url", "")).join(", ") || "-";
}

export function successRate(rows: SourceHealth[]): string {
  if (rows.length === 0) {
    return "-";
  }
  const successCount = rows.reduce((sum, row) => sum + (row.success_count ?? 0), 0);
  const failureCount = rows.reduce((sum, row) => sum + (row.failure_count ?? 0), 0);
  const total = successCount + failureCount;
  return total === 0 ? "-" : `${Math.round((successCount / total) * 100)}%`;
}

export function latestTimestamp(rows: SourceHealth[], field: "last_success_at" | "last_failure_at"): number | null {
  if (rows.length === 0) {
    return null;
  }
  const latest = Math.max(...rows.map((row) => row[field] ?? 0));
  return latest || null;
}
