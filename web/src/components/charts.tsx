import { useState, type ReactNode } from "react";
import type { BudgetRow, Family, FiscalYearMeta, Series } from "../data/types";
import {
  SERIES_ORDER, fmtCompact, fmtFull, fmtPct, hasPct, seriesLabel, seriesShort, val, withSign,
  type Comparison, type TableRow,
} from "../data/model";
import { useWidth } from "./useWidth";

/** Path for a bar with 4px rounded corners on its data end only (anchored flat to the baseline). */
function barPath(x: number, y0: number, w: number, y1: number, horizontal = false, r = 4): string {
  if (horizontal) {
    // y0 = top, w = height, x -> y1 along the x axis
    const [a, b] = [x, y1];
    const len = Math.abs(b - a);
    const rr = Math.min(r, len, w / 2);
    if (b >= a) return `M${a},${y0}H${b - rr}Q${b},${y0} ${b},${y0 + rr}V${y0 + w - rr}Q${b},${y0 + w} ${b - rr},${y0 + w}H${a}Z`;
    return `M${a},${y0}H${b + rr}Q${b},${y0} ${b},${y0 + rr}V${y0 + w - rr}Q${b},${y0 + w} ${b + rr},${y0 + w}H${a}Z`;
  }
  const len = Math.abs(y1 - y0);
  const rr = Math.min(r, len, w / 2);
  if (y1 <= y0) return `M${x},${y0}V${y1 + rr}Q${x},${y1} ${x + rr},${y1}H${x + w - rr}Q${x + w},${y1} ${x + w},${y1 + rr}V${y0}Z`;
  return `M${x},${y0}V${y1 - rr}Q${x},${y1} ${x + rr},${y1}H${x + w - rr}Q${x + w},${y1} ${x + w},${y1 - rr}V${y0}Z`;
}

function niceTicks(min: number, max: number, count = 4): number[] {
  const span = max - min || 1;
  const step0 = span / count;
  const mag = 10 ** Math.floor(Math.log10(step0));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= step0) ?? step0;
  const ticks: number[] = [];
  for (let t = Math.ceil(min / step) * step; t <= max + 1e-9; t += step) ticks.push(Math.round(t / step) * step);
  return ticks;
}

function Tooltip({ x, y, below = false, children }: { x: number; y: number; below?: boolean; children: ReactNode }) {
  return <div className={below ? "tooltip below" : "tooltip"} style={{ left: x, top: y }} role="status">{children}</div>;
}

/** Splits "FY26 Adopted" onto two lines when the band is too narrow for one. */
function AxisLabel({ x, y, text, narrow }: { x: number; y: number; text: string; narrow: boolean }) {
  const parts = narrow ? text.split(" ") : [text];
  return (
    <text x={x} y={y} textAnchor="middle" className="tick">
      {parts.map((t, i) => <tspan key={i} x={x} dy={i ? "1.15em" : 0}>{t}</tspan>)}
    </text>
  );
}

// ---- Release-over-release bars for one budget line --------------------------------------------

export function ReleaseBars({ row, fy, family, cmp }: {
  row: BudgetRow; fy: FiscalYearMeta; family: Family; cmp: Comparison | null;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<Series | null>(null);
  const series = SERIES_ORDER.filter((s) => fy.series.includes(s));
  const values = series.map((s) => val(row, s, family));
  const H = 220, top = 24, bottom = 40, left = 64, right = 8;
  const plotH = H - top - bottom;
  const plotW = Math.max(100, width - left - right);
  const lo = Math.min(0, ...values), hi = Math.max(0, ...values);
  const ticks = niceTicks(lo, hi);
  const dMin = Math.min(lo, ticks[0]), dMax = Math.max(hi, ticks.at(-1)!);
  const y = (v: number) => top + plotH - ((v - dMin) / (dMax - dMin || 1)) * plotH;
  const band = plotW / series.length;
  const bw = Math.min(56, band * 0.6);
  const emphasized = (s: Series) => !cmp || s === cmp.later || s === cmp.earlier;
  const fyn = fy.fiscal_year;

  return (
    <div ref={ref} className="chart">
      <svg width={width} height={H} role="img"
           aria-label={`${row.name}: ${series.map((s, i) => `${seriesLabel(s, fyn)} ${fmtFull(values[i], family)}`).join(", ")}`}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={left} x2={left + plotW} y1={y(t)} y2={y(t)} className={t === 0 ? "axis" : "grid"} />
            <text x={left - 8} y={y(t)} dy="0.32em" textAnchor="end" className="tick">{fmtCompact(t, family)}</text>
          </g>
        ))}
        {series.map((s, i) => {
          const cx = left + band * i + band / 2;
          const v = values[i];
          return (
            <g key={s} onMouseEnter={() => setHover(s)} onMouseLeave={() => setHover(null)}>
              <rect x={left + band * i} y={top} width={band} height={plotH + bottom} fill="transparent" />
              <path d={barPath(cx - bw / 2, y(0), bw, y(v))}
                    className={emphasized(s) ? "bar-accent" : "bar-muted"} opacity={hover && hover !== s ? 0.6 : 1} />
              {emphasized(s) && band >= 72 && (
                <text x={cx} y={v >= 0 ? y(v) - 6 : y(v) + 14} textAnchor="middle" className="value-label">
                  {fmtCompact(v, family)}
                </text>
              )}
              <AxisLabel x={cx} y={H - bottom + 18} text={seriesShort(s, fyn)} narrow={band < 96} />
            </g>
          );
        })}
      </svg>
      {hover && (() => {
        const i = series.indexOf(hover);
        return (
          <Tooltip x={Math.min(left + band * i + band / 2, width - 90)} y={y(Math.max(values[i], 0)) - 8}>
            <strong>{seriesLabel(hover, fyn)}</strong>
            <span>{fmtFull(values[i], family)}</span>
            {fy.releases[hover as keyof typeof fy.releases] && <span className="muted">Published {fy.releases[hover as keyof typeof fy.releases]}</span>}
          </Tooltip>
        );
      })()}
    </div>
  );
}

// ---- Ranked largest cuts / increases among children --------------------------------------------

export function RankedChanges({ rows, kind, family, maxAbs, onSelect, fy, cmp }: {
  rows: TableRow[]; kind: "cut" | "increase"; family: Family; maxAbs: number;
  onSelect: (r: TableRow) => void; fy: number; cmp: Comparison;
}) {
  const [ref, width] = useWidth<HTMLDivElement>(320);
  const [hover, setHover] = useState<number | null>(null);
  const rowH = 30, bh = 12;
  const labelW = Math.min(190, width * 0.42);
  const valueW = 64;
  const plotW = Math.max(40, width - labelW - valueW - 8);
  const x = (v: number) => (Math.abs(v) / (maxAbs || 1)) * plotW;
  const H = Math.max(rows.length, 1) * rowH;

  if (!rows.length) return <p className="muted empty">{kind === "cut" ? "No decreases." : "No increases."}</p>;

  return (
    <div ref={ref} className="chart">
      <svg width={width} height={H} role="img"
           aria-label={`${kind === "cut" ? "Largest decreases" : "Largest increases"}: ${rows.map((r) => `${r.row.name} ${fmtFull(r.change, family)}`).join("; ")}`}>
        {rows.map((r, i) => {
          const y0 = i * rowH;
          const w = Math.max(2, x(r.change));
          return (
            <g key={r.row.codes.join("/")} className="clickable" onClick={() => onSelect(r)}
               onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
              <rect x={0} y={y0} width={width} height={rowH} className={hover === i ? "row-hover" : ""} fill="transparent" />
              <text x={labelW - 8} y={y0 + rowH / 2} dy="0.32em" textAnchor="end" className="label">
                {truncate(r.row.name, Math.floor((labelW - 10) / 8))}
              </text>
              <path d={barPath(labelW, y0 + (rowH - bh) / 2, bh, labelW + w, true)}
                    className={kind === "cut" ? "bar-neg" : "bar-pos"} />
              <text x={labelW + w + 6} y={y0 + rowH / 2} dy="0.32em" className="value-label">
                {withSign(fmtCompact(r.change, family), r.change)}
              </text>
            </g>
          );
        })}
      </svg>
      {hover !== null && rows[hover] && (
        <Tooltip x={Math.max(8, Math.min(labelW - 40, width - 240))} y={hover * rowH + rowH} below>
          <strong>{rows[hover].row.name}</strong>
          <span>{seriesShort(cmp.earlier, fy)}: {fmtFull(rows[hover].earlier, family)}</span>
          <span>{seriesShort(cmp.later, fy)}: {fmtFull(rows[hover].later, family)}</span>
          <span>Change: {withSign(fmtFull(rows[hover].change, family), rows[hover].change)}
            {hasPct(family) && ` (${fmtPct(rows[hover].pct)})`}</span>
        </Tooltip>
      )}
    </div>
  );
}

const truncate = (s: string, n: number) => (s.length > n ? `${s.slice(0, Math.max(1, n - 1))}…` : s);
