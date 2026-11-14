// Shapes of the static JSON written by scripts/build_site_data.py.

export type Columnar = { columns: string[]; rows: (string | number | null)[][] };

export type LevelKey = "agency" | "uoa" | "rc" | "bc" | "oclass" | "ocode";
export type Release = "prelim" | "exec" | "adopt";
export type Series = Release | "prior_adopted" | "prior_modified";
export type Family = "amount" | "position" | "number_of_contracts";

export type LevelMeta = { key: LevelKey; label: string; code: string; name: string };

export type FiscalYearMeta = {
  fiscal_year: number;
  releases: Partial<Record<Release, string>>; // ISO publication dates
  series: Series[];
  families: Family[];
  xlsx: string | null;
  rows: Record<LevelKey, number>;
};

export type SiteIndex = {
  built_at: string;
  source: string;
  pipeline_version: string;
  release_labels: Record<Release, string>;
  levels: LevelMeta[];
  sharded_levels: LevelKey[];
  fiscal_years: FiscalYearMeta[];
};

/** One budget line at some level: codes of itself and every ancestor, its name, and values. */
export type BudgetRow = {
  codes: string[]; // codes[i] = code at level i; length = level index + 1
  name: string;
  values: Record<string, number | null>; // keyed "exec.amount", "prior_adopted.position", ...
};
