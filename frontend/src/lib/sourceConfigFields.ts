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

/** Falls back to general_url, mirroring watch.py's _job_type_url. */
export function sourceConfigFields(company: Company): Array<[string, string | undefined]> {
  const effective = (field: "intern_url" | "newgrad_url" | "fulltime_url") => company[field] || company.general_url;
  const urlFields: Array<[string, string | undefined]> = [
    ["Intern URL", effective("intern_url")],
    ["New grad URL", effective("newgrad_url")],
    ["Full-time URL", effective("fulltime_url")],
    ["General URL", company.general_url],
  ];

  switch (company.source_kind) {
    case "greenhouse":
      return [
        ...urlFields,
        ["Board token", company.board_token],
        [
          "API URL",
          company.board_token && `https://boards-api.greenhouse.io/v1/boards/${company.board_token}/jobs`,
        ],
      ];
    case "ashby":
      return [
        ...urlFields,
        ["Board name", company.board_name],
        ["API URL", company.board_name && `https://api.ashbyhq.com/posting-api/job-board/${company.board_name}`],
      ];
    case "workday":
      return [...urlFields, ["Board token", company.board_token]];
    case "amazon":
      return [...urlFields, ["Fetched via", "https://www.amazon.jobs/en/search.json (fixed, built into the source)"]];
    case "oracle":
      return [...urlFields, ["Fetched via", "Oracle Recruiting Cloud API (full-text search, title-filtered)"]];
    case "sitemap":
      return [...urlFields, ["Fetched via", "public sitemap.xml (titles approximated from URL slugs)"]];
    case "zyte":
    case "apple":
    case "google":
      return urlFields;
    default:
      return [["Config", "Built-in scraper, no per-company URL or token"]];
  }
}
