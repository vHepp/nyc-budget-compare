import type { Family, FiscalYearMeta, LevelMeta, Series } from "./types";
import { SERIES_ORDER, hasPct, seriesLabel, val, type Comparison, type TableRow } from "./model";

const esc = (v: string | number | null) => {
  if (v === null) return "";
  const s = String(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
};

/** CSV of the rows currently shown (filtered + sorted), with every release's value for the metric. */
export function toCsv(rows: TableRow[], levels: LevelMeta[], fy: FiscalYearMeta, family: Family, cmp: Comparison): string {
  if (!rows.length) return "";
  const depth = rows[0].row.codes.length;
  const series: Series[] = SERIES_ORDER.filter((s) => fy.series.includes(s));
  const header = [
    ...levels.slice(0, depth).map((l) => l.code),
    levels[depth - 1].name,
    ...series.map((s) => `${seriesLabel(s, fy.fiscal_year)} ${family}`),
    `change (${cmp.later} vs ${cmp.earlier})`,
    ...(hasPct(family) ? ["pct_change"] : []),
  ];
  const lines = rows.map((r) => [
    ...r.row.codes, r.row.name,
    ...series.map((s) => val(r.row, s, family)),
    r.change,
    ...(hasPct(family) ? [r.pct === null ? null : Number(r.pct.toFixed(6))] : []),
  ]);
  return [header, ...lines].map((l) => l.map(esc).join(",")).join("\n");
}

export function downloadText(filename: string, text: string, type = "text/csv") {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = Object.assign(document.createElement("a"), { href: url, download: filename });
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
