import type { Family, LevelKey } from "../data/types";
import { FAMILIES, LEVEL_KEYS, type SortDir, type SortKey } from "../data/model";

/**
 * All view state lives in the hash URL so any view can be shared:
 *   #/2027/agency/040/uoa/401?cmp=exec~prelim&metric=amount&sort=change&dir=asc&q=school
 */
export type ViewState = {
  fy: number;
  path: string[]; // codes, one per level from the top (agency first)
  cmp: string | null;
  metric: Family;
  sort: SortKey;
  dir: SortDir;
  q: string;
};

const SORT_KEYS: SortKey[] = ["name", "code", "earlier", "later", "change", "pct"];
export const DEFAULT_SORT: SortKey = "change";
export const DEFAULT_DIR: SortDir = "asc"; // biggest cuts first

/** Parses the path part after the fiscal year: "agency/040/uoa/401" -> ["040", "401"]. */
export function parsePath(segments: string[]): string[] {
  const path: string[] = [];
  for (let i = 0; i + 1 < segments.length; i += 2) {
    if (segments[i] !== LEVEL_KEYS[path.length]) break; // levels must appear in order
    path.push(decodeURIComponent(segments[i + 1]));
  }
  return path;
}

export function parseView(fy: number, splat: string, params: URLSearchParams): ViewState {
  const metric = params.get("metric") as Family;
  const sort = params.get("sort") as SortKey;
  const dir = params.get("dir");
  return {
    fy,
    path: parsePath(splat.split("/").filter(Boolean)),
    cmp: params.get("cmp"),
    metric: FAMILIES.includes(metric) ? metric : "amount",
    sort: SORT_KEYS.includes(sort) ? sort : DEFAULT_SORT,
    dir: dir === "asc" || dir === "desc" ? dir : DEFAULT_DIR,
    q: params.get("q") ?? "",
  };
}

export function pathSegments(path: string[]): string {
  return path.map((code, i) => `${LEVEL_KEYS[i] as LevelKey}/${encodeURIComponent(code)}`).join("/");
}

/** Builds a router path (without "#"). Defaults are omitted to keep shared links short. */
export function viewHref(v: ViewState): string {
  const p = new URLSearchParams();
  if (v.cmp) p.set("cmp", v.cmp);
  if (v.metric !== "amount") p.set("metric", v.metric);
  if (v.sort !== DEFAULT_SORT) p.set("sort", v.sort);
  if (v.dir !== DEFAULT_DIR) p.set("dir", v.dir);
  if (v.q) p.set("q", v.q);
  const segs = pathSegments(v.path);
  const qs = p.toString();
  return `/${v.fy}${segs ? `/${segs}` : ""}${qs ? `?${qs}` : ""}`;
}
