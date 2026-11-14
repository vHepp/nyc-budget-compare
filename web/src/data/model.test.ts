import { describe, expect, it } from "vitest";
import type { BudgetRow, FiscalYearMeta } from "./types";
import { availableComparisons, buildTableRows, change, cmpId, fmtCompact, fmtPct, resolveComparison, sumRows } from "./model";
import { parseColumnar } from "./load";
import { parseView, viewHref } from "../state/url";

const fy = (series: FiscalYearMeta["series"]): FiscalYearMeta =>
  ({ fiscal_year: 2027, releases: {}, series, families: ["amount"], xlsx: null, rows: {} as FiscalYearMeta["rows"] });

const row = (code: string, name: string, prelim: number, exec: number): BudgetRow =>
  ({ codes: ["040", code], name, values: { "prelim.amount": prelim, "exec.amount": exec } });

describe("comparisons", () => {
  it("offers release pairs then prior-year baselines, latest first", () => {
    const ids = availableComparisons(fy(["prelim", "exec", "adopt", "prior_adopted"])).map(cmpId);
    expect(ids).toEqual(["adopt~exec", "adopt~prelim", "exec~prelim", "adopt~prior_adopted", "exec~prior_adopted", "prelim~prior_adopted"]);
  });
  it("falls back to vs prior adopted when only prelim exists, and rejects unavailable ids", () => {
    const meta = fy(["prelim", "prior_adopted"]);
    expect(cmpId(resolveComparison(meta, "adopt~exec")!)).toBe("prelim~prior_adopted");
  });
});

describe("change", () => {
  it("matches apiv8: pct is null when the base is zero", () => {
    expect(change(row("1", "A", 100, 80), { later: "exec", earlier: "prelim" }, "amount"))
      .toEqual({ earlier: 100, later: 80, change: -20, pct: -0.2 });
    expect(change(row("2", "B", 0, 50), { later: "exec", earlier: "prelim" }, "amount").pct).toBeNull();
  });
  it("sums rows for citywide", () => {
    expect(sumRows([row("1", "A", 1, 2), row("2", "B", 3, 4)], "C").values).toEqual({ "prelim.amount": 4, "exec.amount": 6 });
  });
});

describe("table rows", () => {
  const rows = [row("1", "Alpha", 100, 80), row("2", "Beta", 0, 50), row("3", "Gamma", 10, 5)];
  const cmp = { later: "exec", earlier: "prelim" } as const;
  it("sorts by change ascending (largest cut first)", () => {
    expect(buildTableRows(rows, cmp, "amount", "", "change", "asc").map((r) => r.row.name)).toEqual(["Alpha", "Gamma", "Beta"]);
  });
  it("puts null pct last in both directions and filters by name or code", () => {
    expect(buildTableRows(rows, cmp, "amount", "", "pct", "desc").at(-1)!.row.name).toBe("Beta");
    expect(buildTableRows(rows, cmp, "amount", "gam", "change", "asc").map((r) => r.row.name)).toEqual(["Gamma"]);
    expect(buildTableRows(rows, cmp, "amount", "2", "change", "asc").map((r) => r.row.name)).toEqual(["Beta"]);
  });
});

describe("parseColumnar", () => {
  it("splits codes, name, and values by level", () => {
    const [r] = parseColumnar({ columns: ["agency_number", "unit_appropriation_number", "unit_appropriation_name", "exec.amount"],
                                rows: [["040", "401", "GEN ED", 12]] }, 1);
    expect(r).toEqual({ codes: ["040", "401"], name: "GEN ED", values: { "exec.amount": 12 } });
  });
});

describe("url state", () => {
  it("round-trips a view and omits defaults", () => {
    const v = parseView(2027, "agency/040/uoa/401", new URLSearchParams("cmp=exec~prelim&metric=position&q=school"));
    expect(v.path).toEqual(["040", "401"]);
    expect(viewHref(v)).toBe("/2027/agency/040/uoa/401?cmp=exec%7Eprelim&metric=position&q=school");
    expect(viewHref({ ...v, path: [], cmp: null, metric: "amount", q: "" })).toBe("/2027");
  });
  it("ignores out-of-order levels", () => {
    expect(parseView(2027, "uoa/401", new URLSearchParams()).path).toEqual([]);
  });
});

describe("format", () => {
  it("formats compact amounts and signed pct", () => {
    expect(fmtCompact(1_234_000_000, "amount")).toBe("$1.2B");
    expect(fmtCompact(-350_400, "amount")).toBe("−$350.4K");
    expect(fmtPct(-0.123)).toBe("−12.3%");
    expect(fmtPct(null)).toBe("—");
  });
});
