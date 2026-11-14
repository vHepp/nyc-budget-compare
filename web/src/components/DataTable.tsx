import { useRef } from "react";
import { Link } from "react-router-dom";
import { useVirtualizer } from "@tanstack/react-virtual";
import type { Family } from "../data/types";
import {
  fmtFull, fmtPct, hasPct, seriesShort, withSign,
  type Comparison, type SortDir, type SortKey, type TableRow,
} from "../data/model";

type Props = {
  rows: TableRow[];
  family: Family;
  cmp: Comparison;
  fy: number;
  sort: SortKey;
  dir: SortDir;
  onSort: (k: SortKey) => void;
  hrefFor: (r: TableRow) => string;
};

const ROW_H = 40;

function ChangeCell({ v, family }: { v: number; family: Family }) {
  return (
    <span className="change">
      {v !== 0 && <span className={v < 0 ? "glyph neg" : "glyph pos"} aria-hidden>{v < 0 ? "▼" : "▲"}</span>}
      {withSign(fmtFull(v, family), v)}
    </span>
  );
}

export function DataTable({ rows, family, cmp, fy, sort, dir, onSort, hrefFor }: Props) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const virt = useVirtualizer({ count: rows.length, getScrollElement: () => scrollRef.current,
                                estimateSize: () => ROW_H, overscan: 12 });
  const pct = hasPct(family);
  const cols: { key: SortKey; label: string; num?: boolean }[] = [
    { key: "code", label: "Code" },
    { key: "name", label: "Name" },
    { key: "earlier", label: seriesShort(cmp.earlier, fy), num: true },
    { key: "later", label: seriesShort(cmp.later, fy), num: true },
    { key: "change", label: "Change", num: true },
    ...(pct ? [{ key: "pct" as SortKey, label: "% change", num: true }] : []),
  ];
  const gridClass = pct ? "grid6" : "grid5";

  return (
    <div className="table-wrap">
      <div className="table-scroll" ref={scrollRef} role="table" aria-rowcount={rows.length + 1}>
        <div className={`tr th ${gridClass}`} role="row">
          {cols.map((c) => (
            <div key={c.key} role="columnheader" className={c.num ? "num" : ""}
                 aria-sort={sort === c.key ? (dir === "asc" ? "ascending" : "descending") : "none"}>
              <button type="button" onClick={() => onSort(c.key)}>
                {c.label}{sort === c.key ? (dir === "asc" ? " ↑" : " ↓") : ""}
              </button>
            </div>
          ))}
        </div>
        <div style={{ height: virt.getTotalSize(), position: "relative" }}>
          {virt.getVirtualItems().map((vi) => {
            const r = rows[vi.index];
            return (
              <Link key={r.row.codes.join("/")} to={hrefFor(r)} role="row"
                    className={`tr ${gridClass}`}
                    style={{ position: "absolute", top: 0, left: 0, right: 0, height: ROW_H, transform: `translateY(${vi.start}px)` }}>
                <div role="cell" className="code">{r.row.codes.at(-1)}</div>
                <div role="cell" className="name" title={r.row.name}>{r.row.name}</div>
                <div role="cell" className="num">{fmtFull(r.earlier, family)}</div>
                <div role="cell" className="num">{fmtFull(r.later, family)}</div>
                <div role="cell" className="num"><ChangeCell v={r.change} family={family} /></div>
                {pct && <div role="cell" className="num">{fmtPct(r.pct)}</div>}
              </Link>
            );
          })}
        </div>
        {!rows.length && <p className="muted empty">No matching lines.</p>}
      </div>
    </div>
  );
}
