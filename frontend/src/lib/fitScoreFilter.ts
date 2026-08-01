export type ComparisonOperator = ">=" | "<=" | ">" | "<" | "=";

export interface FitScoreFilter {
  operator: ComparisonOperator;
  value: number;
}

const FILTER_PATTERN = /^\s*(>=|<=|>|<|=)?\s*(\d+)\s*$/;

/** "90" means equality, ">=90" compares; anything else disables the filter. */
export function parseFitScoreFilter(raw: string): FitScoreFilter | null {
  const match = FILTER_PATTERN.exec(raw);
  const digits = match?.[2];
  if (digits === undefined) {
    return null;
  }
  return { operator: (match?.[1] as ComparisonOperator | undefined) ?? "=", value: Number(digits) };
}

export function matchesFitScore(filter: FitScoreFilter, score: number): boolean {
  switch (filter.operator) {
    case ">=":
      return score >= filter.value;
    case "<=":
      return score <= filter.value;
    case ">":
      return score > filter.value;
    case "<":
      return score < filter.value;
    case "=":
      return score === filter.value;
  }
}
