export type ComparisonOperator = ">=" | "<=" | ">" | "<" | "=";

export interface FitScoreFilter {
  operator: ComparisonOperator;
  value: number;
}

const FILTER_PATTERN = /^\s*(>=|<=|>|<|=)?\s*(\d+)\s*$/;

/** Accepts a bare number ("90" means exactly 90) or one prefixed with a
 * comparison operator (">=90", "<90"); anything else disables the filter. */
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
