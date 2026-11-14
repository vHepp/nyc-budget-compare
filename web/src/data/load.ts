import type { BudgetRow, Columnar, LevelKey, SiteIndex } from "./types";
import { LEVEL_KEYS } from "./model";

const cache = new Map<string, Promise<unknown>>();

export function dataUrl(path: string): string {
  return `${import.meta.env.BASE_URL}data/${path}`;
}

function fetchJson<T>(path: string): Promise<T> {
  let p = cache.get(path) as Promise<T> | undefined;
  if (!p) {
    p = fetch(dataUrl(path)).then((r) => {
      if (!r.ok) throw new Error(`Failed to load ${path} (${r.status})`);
      return r.json() as Promise<T>;
    });
    p.catch(() => cache.delete(path)); // allow retry after a failure
    cache.set(path, p);
  }
  return p;
}

/** Converts the columnar format into BudgetRows. The first `level + 1` columns are codes, then the name. */
export function parseColumnar(data: Columnar, levelIndex: number): BudgetRow[] {
  const nCodes = levelIndex + 1;
  const valueCols = data.columns.slice(nCodes + 1);
  return data.rows.map((r) => {
    const values: Record<string, number | null> = {};
    valueCols.forEach((c, i) => (values[c] = r[nCodes + 1 + i] as number | null));
    return { codes: r.slice(0, nCodes) as string[], name: r[nCodes] as string, values };
  });
}

export const loadIndex = () => fetchJson<SiteIndex>("index.json");

const parsed = new Map<string, Promise<BudgetRow[]>>();

/**
 * All rows of a level. Sharded levels (bc, oclass, ocode) are only available per agency,
 * so `agency` is required for them.
 */
export function loadLevel(index: SiteIndex, fy: number, level: LevelKey, agency?: string): Promise<BudgetRow[]> {
  const li = LEVEL_KEYS.indexOf(level);
  const sharded = index.sharded_levels.includes(level);
  if (sharded && !agency) throw new Error(`Level ${level} requires an agency`);
  const key = sharded ? `${fy}/${level}/${agency}` : `${fy}/${level}`;
  let p = parsed.get(key);
  if (!p) {
    p = sharded
      ? fetchJson<Record<string, Columnar>>(`fy${fy}/by_agency/${agency}.json`).then((s) =>
          parseColumnar(s[level] ?? { columns: [], rows: [] }, li),
        )
      : fetchJson<Columnar>(`fy${fy}/${level}.json`).then((d) => parseColumnar(d, li));
    p.catch(() => parsed.delete(key));
    parsed.set(key, p);
  }
  return p;
}
