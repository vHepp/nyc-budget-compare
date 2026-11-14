import type { BudgetRow, Family, FiscalYearMeta, LevelKey, Release, Series } from "./types";

export const LEVEL_KEYS: LevelKey[] = ["agency", "uoa", "rc", "bc", "oclass", "ocode"];
export const RELEASES: Release[] = ["prelim", "exec", "adopt"];
export const SERIES_ORDER: Series[] = ["prior_adopted", "prior_modified", "prelim", "exec", "adopt"];
export const FAMILIES: Family[] = ["amount", "position", "number_of_contracts"];

export const FAMILY_LABELS: Record<Family, string> = {
  amount: "Dollars",
  position: "Positions",
  number_of_contracts: "Contracts",
};

/** Matches apiv8.PCT_CHANGE_FAMILIES: % change is only meaningful for dollar amounts. */
export const hasPct = (f: Family) => f === "amount";

export function seriesLabel(s: Series, fy: number): string {
  switch (s) {
    case "prelim": return `FY${fy % 100} Preliminary`;
    case "exec": return `FY${fy % 100} Executive`;
    case "adopt": return `FY${fy % 100} Adopted`;
    case "prior_adopted": return `FY${(fy - 1) % 100} Adopted`;
    case "prior_modified": return `FY${(fy - 1) % 100} Modified`;
  }
}

export const seriesShort = (s: Series, fy: number) =>
  ({ prelim: "Prelim", exec: "Exec", adopt: "Adopted",
     prior_adopted: `FY${(fy - 1) % 100} Adopted`, prior_modified: `FY${(fy - 1) % 100} Modified` })[s];

// ---- Comparisons ---------------------------------------------------------------------------

export type Comparison = { later: Series; earlier: Series };

export const cmpId = (c: Comparison) => `${c.later}~${c.earlier}`;

export function parseCmp(id: string | null): Comparison | null {
  if (!id) return null;
  const [later, earlier] = id.split("~") as Series[];
  return later && earlier ? { later, earlier } : null;
}

/** Same pairs apiv8.calculate_differences produces: release vs earlier release, release vs prior-year baselines. */
export function availableComparisons(fy: FiscalYearMeta): Comparison[] {
  const rel = RELEASES.filter((r) => fy.series.includes(r));
  const out: Comparison[] = [];
  for (let i = rel.length - 1; i >= 0; i--) {
    for (let j = i - 1; j >= 0; j--) out.push({ later: rel[i], earlier: rel[j] });
  }
  for (const base of ["prior_adopted", "prior_modified"] as Series[]) {
    if (!fy.series.includes(base)) continue;
    for (let i = rel.length - 1; i >= 0; i--) out.push({ later: rel[i], earlier: base });
  }
  return out;
}

/** Default: the latest release vs the one before it; with a single release, vs prior-year adopted. */
export function defaultComparison(fy: FiscalYearMeta): Comparison | null {
  return availableComparisons(fy)[0] ?? null;
}

export function resolveComparison(fy: FiscalYearMeta, id: string | null): Comparison | null {
  const all = availableComparisons(fy);
  const want = parseCmp(id);
  return (want && all.find((c) => cmpId(c) === cmpId(want))) || all[0] || null;
}

export const cmpLabel = (c: Comparison, fy: number) =>
  `${seriesShort(c.later, fy)} vs ${seriesShort(c.earlier, fy)}`;

// ---- Values and changes ---------------------------------------------------------------------

export const val = (r: BudgetRow, s: Series, f: Family): number => r.values[`${s}.${f}`] ?? 0;

export type Change = { earlier: number; later: number; change: number; pct: number | null };

/** Same as apiv8: change = later - earlier; pct = change / earlier, null when earlier is 0. */
export function change(r: BudgetRow, c: Comparison, f: Family): Change {
  const earlier = val(r, c.earlier, f);
  const later = val(r, c.later, f);
  const d = later - earlier;
  return { earlier, later, change: d, pct: earlier === 0 ? null : d / earlier };
}

/** Sums rows into one synthetic row (used for the citywide total). */
export function sumRows(rows: BudgetRow[], name: string): BudgetRow {
  const values: Record<string, number> = {};
  for (const r of rows) {
    for (const [k, v] of Object.entries(r.values)) values[k] = (values[k] ?? 0) + (v ?? 0);
  }
  return { codes: [], name, values };
}

// ---- Hierarchy ------------------------------------------------------------------------------

export const isPrefix = (prefix: string[], codes: string[]) => prefix.every((c, i) => codes[i] === c);

export const childrenOf = (rows: BudgetRow[], path: string[]) => rows.filter((r) => isPrefix(path, r.codes));

export const findRow = (rows: BudgetRow[], path: string[]) =>
  rows.find((r) => r.codes.length === path.length && isPrefix(path, r.codes));

// ---- Sorting & filtering --------------------------------------------------------------------

export type SortKey = "name" | "code" | "earlier" | "later" | "change" | "pct";
export type SortDir = "asc" | "desc";

export type TableRow = { row: BudgetRow } & Change;

export function buildTableRows(rows: BudgetRow[], c: Comparison, f: Family, q: string,
                               sort: SortKey, dir: SortDir): TableRow[] {
  const needle = q.trim().toLowerCase();
  const out = rows
    .filter((r) => !needle || r.name.toLowerCase().includes(needle) || r.codes.at(-1)!.toLowerCase().includes(needle))
    .map((row) => ({ row, ...change(row, c, f) }));
  const sign = dir === "asc" ? 1 : -1;
  const key = (t: TableRow): string | number | null =>
    sort === "name" ? t.row.name : sort === "code" ? t.row.codes.at(-1)! : t[sort];
  return out.sort((a, b) => {
    const ka = key(a), kb = key(b);
    if (ka === null && kb === null) return 0;
    if (ka === null) return 1; // nulls (no % change) always last
    if (kb === null) return -1;
    return (typeof ka === "string" ? ka.localeCompare(kb as string) : ka - (kb as number)) * sign;
  });
}

// ---- Formatting -----------------------------------------------------------------------------

const full = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const dec = new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 });

export function fmtFull(v: number, f: Family): string {
  const s = full.format(Math.abs(v));
  const sign = v < 0 ? "−" : "";
  return f === "amount" ? `${sign}$${s}` : `${sign}${s}`;
}

export function fmtCompact(v: number, f: Family): string {
  const a = Math.abs(v);
  const sign = v < 0 ? "−" : "";
  const [n, u] = a >= 1e9 ? [a / 1e9, "B"] : a >= 1e6 ? [a / 1e6, "M"] : a >= 1e3 ? [a / 1e3, "K"] : [a, ""];
  const num = u ? dec.format(n) : full.format(n);
  return f === "amount" ? `${sign}$${num}${u}` : `${sign}${num}${u}`;
}

export const withSign = (s: string, v: number) => (v > 0 ? `+${s}` : s);

export function fmtPct(p: number | null): string {
  if (p === null) return "—";
  const s = `${dec.format(Math.abs(p * 100))}%`;
  return p > 0 ? `+${s}` : p < 0 ? `−${s}` : s;
}
