import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import type { Family, SiteIndex } from "../data/types";
import {
  FAMILY_LABELS, availableComparisons, buildTableRows, cmpId, cmpLabel, fmtCompact, fmtFull, fmtPct,
  hasPct, resolveComparison, seriesLabel, withSign, change, type SortKey, type TableRow,
} from "../data/model";
import { useNode } from "../data/useNode";
import { dataUrl } from "../data/load";
import { downloadText, toCsv } from "../data/csv";
import { parseView, viewHref, type ViewState } from "../state/url";
import { RankedChanges, ReleaseBars } from "../components/charts";
import { DataTable } from "../components/DataTable";

const TOP_N = 8;
const PLURALS: Record<string, string> = {
  agency: "Agencies", uoa: "Units of appropriation", rc: "Responsibility centers",
  bc: "Budget codes", oclass: "Object classes", ocode: "Object codes",
};

export function Explorer({ index }: { index: SiteIndex }) {
  const params = useParams();
  const [search] = useSearchParams();
  const navigate = useNavigate();
  const fyNum = Number(params.fy);
  const fy = index.fiscal_years.find((f) => f.fiscal_year === fyNum);
  const view = parseView(fyNum, params["*"] ?? "", search);
  const node = useNode(index, fyNum, view.path);
  const [copied, setCopied] = useState(false);
  const [q, setQ] = useState(view.q);
  useEffect(() => setQ(view.q), [view.q]);

  const cmp = fy ? resolveComparison(fy, view.cmp) : null;
  const go = (patch: Partial<ViewState>, replace = false) =>
    navigate(viewHref({ ...view, ...patch }), { replace });

  // Debounce search typing into the URL (replace, so it doesn't spam history).
  useEffect(() => {
    if (q === view.q) return;
    const t = setTimeout(() => go({ q }, true), 250);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q]);

  const children = node.status === "ready" ? node.data.children : [];
  const tableRows = useMemo(
    () => (cmp ? buildTableRows(children, cmp, view.metric, view.q, view.sort, view.dir) : []),
    [children, cmp && cmpId(cmp), view.metric, view.q, view.sort, view.dir], // eslint-disable-line react-hooks/exhaustive-deps
  );
  const ranked = useMemo(() => {
    if (!cmp) return { cuts: [], incs: [], maxAbs: 0 };
    const all = buildTableRows(children, cmp, view.metric, "", "change", "asc");
    const cuts = all.filter((r) => r.change < 0).slice(0, TOP_N);
    const incs = all.filter((r) => r.change > 0).reverse().slice(0, TOP_N);
    const maxAbs = Math.max(0, ...cuts.map((r) => -r.change), ...incs.map((r) => r.change));
    return { cuts, incs, maxAbs };
  }, [children, cmp && cmpId(cmp), view.metric]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!fy) {
    return <div className="notice">No data for FY{params.fy}. <Link to={`/${index.fiscal_years[0].fiscal_year}`}>Go to the latest year</Link>.</div>;
  }
  if (!cmp) return <div className="notice">FY{fyNum} has no releases to compare yet.</div>;

  const childHref = (r: TableRow) => viewHref({ ...view, path: r.row.codes, q: "" });
  const levelLabel = (i: number) => index.levels[i]?.label ?? "";

  const onSort = (k: SortKey) =>
    // First click: text A→Z, changes most-negative first (cuts), amounts largest first.
    go(view.sort === k ? { dir: view.dir === "asc" ? "desc" : "asc" }
                       : { sort: k, dir: k === "earlier" || k === "later" ? "desc" : "asc" }, true);

  const copyLink = async () => {
    try {
      await navigator.clipboard.writeText(window.location.href);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      window.prompt("Copy this link:", window.location.href);
    }
  };

  const exportCsv = () => {
    const name = node.status === "ready" ? node.data.self.name : "citywide";
    const slug = name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 40);
    downloadText(`FY${fyNum % 100}_${slug}_${node.status === "ready" ? node.data.childLevel : "lines"}.csv`,
                 toCsv(tableRows, index.levels, fy, view.metric, cmp));
  };

  return (
    <>
      <nav className="breadcrumbs" aria-label="Breadcrumb">
        <Link to={viewHref({ ...view, path: [], q: "" })}>Citywide</Link>
        {node.status === "ready" && node.data.trail.map((r, i) => (
          <span key={i}>
            <span className="sep" aria-hidden>›</span>
            {i === node.data.trail.length - 1
              ? <span aria-current="page">{r.name}</span>
              : <Link to={viewHref({ ...view, path: r.codes, q: "" })}>{r.name}</Link>}
          </span>
        ))}
      </nav>

      <div className="controls" role="group" aria-label="View options">
        <label>
          <span>Fiscal year</span>
          <select value={fyNum} onChange={(e) => go({ fy: Number(e.target.value), cmp: null })}>
            {index.fiscal_years.map((f) => <option key={f.fiscal_year} value={f.fiscal_year}>FY{f.fiscal_year}</option>)}
          </select>
        </label>
        <label>
          <span>Compare</span>
          <select value={cmpId(cmp)} onChange={(e) => go({ cmp: e.target.value })}>
            {availableComparisons(fy).map((c) => <option key={cmpId(c)} value={cmpId(c)}>{cmpLabel(c, fyNum)}</option>)}
          </select>
        </label>
        <div className="segmented" role="radiogroup" aria-label="Measure">
          {fy.families.map((f: Family) => (
            <button key={f} type="button" role="radio" aria-checked={view.metric === f}
                    className={view.metric === f ? "on" : ""} onClick={() => go({ metric: f })}>
              {FAMILY_LABELS[f]}
            </button>
          ))}
        </div>
        <div className="actions">
          <button type="button" onClick={copyLink}>{copied ? "Link copied" : "Copy link"}</button>
          <button type="button" onClick={exportCsv} disabled={!tableRows.length}>Download CSV</button>
          {fy.xlsx && <a className="button" href={dataUrl(`fy${fyNum}/${fy.xlsx}`)} download>Full workbook (.xlsx)</a>}
        </div>
      </div>

      {node.status === "loading" && <div className="notice">Loading…</div>}
      {node.status === "error" && <div className="notice">Couldn't load data: {node.error}</div>}
      {node.status === "notfound" && (
        <div className="notice">This line doesn't exist in FY{fyNum}. <Link to={viewHref({ ...view, path: [], q: "" })}>Back to citywide</Link>.</div>
      )}

      {node.status === "ready" && (() => {
        const { self, childLevel } = node.data;
        const c = change(self, cmp, view.metric);
        const depth = view.path.length;
        return (
          <>
            <header className="node-head">
              <p className="eyebrow">{depth === 0 ? `FY${fyNum} expense budget` : `${levelLabel(depth - 1)} ${view.path.at(-1)}`}</p>
              <h1>{self.name}</h1>
            </header>

            <section className="tiles" aria-label="Summary">
              <div className="tile"><span className="tile-label">{seriesLabel(cmp.earlier, fyNum)}</span>
                <span className="tile-value">{fmtCompact(c.earlier, view.metric)}</span></div>
              <div className="tile"><span className="tile-label">{seriesLabel(cmp.later, fyNum)}</span>
                <span className="tile-value">{fmtCompact(c.later, view.metric)}</span></div>
              <div className="tile"><span className="tile-label">Change</span>
                <span className="tile-value">
                  {c.change !== 0 && <span className={c.change < 0 ? "glyph neg" : "glyph pos"} aria-hidden>{c.change < 0 ? "▼" : "▲"}</span>}
                  {withSign(fmtCompact(c.change, view.metric), c.change)}
                </span>
                {hasPct(view.metric) && <span className="tile-sub">{fmtPct(c.pct)} · {withSign(fmtFull(c.change, view.metric), c.change)}</span>}
              </div>
            </section>

            <section className="card">
              <h2>{FAMILY_LABELS[view.metric]} by release</h2>
              <p className="muted small">The two releases being compared are highlighted.</p>
              <ReleaseBars row={self} fy={fy} family={view.metric} cmp={cmp} />
            </section>

            {childLevel ? (
              <>
                <section className="two-up">
                  <div className="card">
                    <h2>Largest decreases <span className="muted">by {levelLabel(depth)}</span></h2>
                    <RankedChanges rows={ranked.cuts} kind="cut" family={view.metric} maxAbs={ranked.maxAbs}
                                   onSelect={(r) => navigate(childHref(r))} fy={fyNum} cmp={cmp} />
                  </div>
                  <div className="card">
                    <h2>Largest increases <span className="muted">by {levelLabel(depth)}</span></h2>
                    <RankedChanges rows={ranked.incs} kind="increase" family={view.metric} maxAbs={ranked.maxAbs}
                                   onSelect={(r) => navigate(childHref(r))} fy={fyNum} cmp={cmp} />
                  </div>
                </section>

                <section className="card">
                  <div className="card-head">
                    <h2>{PLURALS[childLevel]} <span className="muted">({tableRows.length.toLocaleString()} of {children.length.toLocaleString()})</span></h2>
                    <input type="search" placeholder={`Search ${levelLabel(depth).toLowerCase()} name or code`}
                           value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search" />
                  </div>
                  <DataTable rows={tableRows} family={view.metric} cmp={cmp} fy={fyNum}
                             sort={view.sort} dir={view.dir} onSort={onSort} hrefFor={childHref} />
                </section>
              </>
            ) : (
              <p className="muted">This is the most detailed level in the dataset (object code).</p>
            )}
          </>
        );
      })()}
    </>
  );
}
