import type { SiteIndex } from "../data/types";

export function About({ index }: { index: SiteIndex }) {
  const built = new Date(index.built_at);
  return (
    <article className="prose">
      <h1>About this explorer</h1>
      <p>
        New York City publishes its expense budget three times for each fiscal year. This site shows what changed between
        those releases for every agency and budget line, so community groups can spot cuts and restorations, cite exact
        figures, and share a link to a specific view.
      </p>

      <h2>The releases</h2>
      <dl>
        <dt>Preliminary</dt><dd>The Mayor's first proposal for the fiscal year, usually published in January or February.</dd>
        <dt>Executive</dt><dd>The Mayor's revised proposal after City Council hearings, usually published in late April or May.</dd>
        <dt>Adopted</dt><dd>The budget agreed by the Mayor and Council, published around June 30, before the fiscal year starts on July 1.</dd>
        <dt>Prior-year Adopted / Modified</dt><dd>The previous fiscal year's adopted budget, and its current modified budget
          (the adopted budget plus changes made during the year). The modified budget is the closest available figure to actual spending.</dd>
      </dl>

      <h2>How changes are calculated</h2>
      <p>
        Change = later release − earlier release. Percent change = change ÷ earlier release. It is only shown for dollars,
        and is left blank when the earlier value is zero. Positions are full-time headcount, and contracts are the number of contracts.
      </p>
      <p>
        Amounts are <em>financial plan</em> amounts for the fiscal year as published in each release. Each level (agency → unit of
        appropriation → responsibility center → budget code → object class → object code) is the sum of the lines beneath it.
      </p>

      <h2>Data</h2>
      <ul>
        <li>Source: <a href={index.source}>NYC Open Data, Expense Budget dataset</a>.</li>
        <li>Last refreshed: {built.toLocaleString()} (pipeline v{index.pipeline_version}).</li>
        <li>Publication dates:
          <ul>
            {index.fiscal_years.map((f) => (
              <li key={f.fiscal_year}>FY{f.fiscal_year}: {Object.entries(f.releases).map(([r, d]) =>
                `${index.release_labels[r as keyof typeof index.release_labels]} ${d}`).join(" · ")}</li>
            ))}
          </ul>
        </li>
      </ul>
      <p className="muted">
        This is an independent project, not an official City of New York publication. Check important figures against the
        official budget documents before you cite them.
      </p>
    </article>
  );
}
