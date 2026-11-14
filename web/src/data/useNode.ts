import { useEffect, useState } from "react";
import type { BudgetRow, LevelKey, SiteIndex } from "./types";
import { LEVEL_KEYS, childrenOf, findRow, sumRows } from "./model";
import { loadLevel } from "./load";

export type NodeData = {
  /** Rows for each path segment (ancestors then self); empty at citywide. */
  trail: BudgetRow[];
  self: BudgetRow;
  childLevel: LevelKey | null; // null at the most detailed level
  children: BudgetRow[];
};

type State = { status: "loading" } | { status: "error"; error: string } | { status: "notfound" }
  | { status: "ready"; data: NodeData };

export function useNode(index: SiteIndex | null, fy: number, path: string[]): State {
  const [state, setState] = useState<State>({ status: "loading" });
  const key = `${fy}|${path.join("/")}`;

  useEffect(() => {
    if (!index) return;
    let cancelled = false;
    setState({ status: "loading" });
    const depth = path.length;
    const levelsNeeded = LEVEL_KEYS.slice(0, Math.min(depth + 1, LEVEL_KEYS.length));
    Promise.all(levelsNeeded.map((lv) => loadLevel(index, fy, lv, path[0])))
      .then((levels) => {
        if (cancelled) return;
        const trail: BudgetRow[] = [];
        for (let i = 0; i < depth; i++) {
          const r = findRow(levels[i], path.slice(0, i + 1));
          if (!r) return setState({ status: "notfound" });
          trail.push(r);
        }
        const childLevel = depth < LEVEL_KEYS.length ? LEVEL_KEYS[depth] : null;
        const children = childLevel ? childrenOf(levels[depth], path) : [];
        const self = depth === 0 ? sumRows(levels[0], "Citywide") : trail[depth - 1];
        setState({ status: "ready", data: { trail, self, childLevel, children } });
      })
      .catch((e: Error) => !cancelled && setState({ status: "error", error: e.message }));
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [index, key]);

  return state;
}
