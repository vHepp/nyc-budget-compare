import { useEffect, useState } from "react";
import { HashRouter, Link, NavLink, Navigate, Route, Routes } from "react-router-dom";
import type { SiteIndex } from "./data/types";
import { loadIndex } from "./data/load";
import { Explorer } from "./pages/Explorer";
import { About } from "./pages/About";

export default function App() {
  const [index, setIndex] = useState<SiteIndex | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadIndex().then(setIndex).catch((e: Error) => setError(e.message));
  }, []);

  const latest = index?.fiscal_years[0]?.fiscal_year;

  return (
    <HashRouter>
      <div className="app">
        <header className="topbar">
          <Link to="/" className="brand">NYC Budget Compare</Link>
          <nav>
            {latest && <NavLink to={`/${latest}`} end={false}>Explore</NavLink>}
            <NavLink to="/about">About</NavLink>
          </nav>
        </header>
        <main>
          {error && <div className="notice">Couldn't load the site data ({error}). Run <code>scripts/build_site_data.py</code> to generate it.</div>}
          {!index && !error && <div className="notice">Loading…</div>}
          {index && (
            <Routes>
              <Route path="/" element={latest ? <Navigate to={`/${latest}`} replace /> : <div className="notice">No data.</div>} />
              <Route path="/about" element={<About index={index} />} />
              <Route path="/:fy/*" element={<Explorer index={index} />} />
            </Routes>
          )}
        </main>
        <footer className="footer muted small">
          Data: <a href={index?.source ?? "https://data.cityofnewyork.us/"}>NYC Open Data</a>
          {index && <> · refreshed {new Date(index.built_at).toLocaleDateString()}</>}
        </footer>
      </div>
    </HashRouter>
  );
}
