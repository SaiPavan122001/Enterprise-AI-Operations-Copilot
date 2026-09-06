import { useMemo, useState } from "react";

function formatHistoryTime(ts) {
  try {
    const date = new Date(ts);
    const now = new Date();
    const sameDay = date.toDateString() === now.toDateString();
    const yesterday = new Date(now);
    yesterday.setDate(now.getDate() - 1);
    const opts = { hour: "2-digit", minute: "2-digit" };
    if (sameDay) return `Today, ${date.toLocaleTimeString(undefined, opts)}`;
    if (date.toDateString() === yesterday.toDateString()) return "Yesterday";
    return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  } catch {
    return "";
  }
}

export default function Sidebar({ history, onSelect, onNew, open, onClose }) {
  const [query, setQuery] = useState("");

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return history;
    return history.filter((item) =>
      `${item.question} ${item.summary || ""}`.toLowerCase().includes(q)
    );
  }, [history, query]);

  return (
    <>
      <div
        className={`sidebar-backdrop ${open ? "visible" : ""}`}
        onClick={onClose}
        aria-hidden="true"
      />
      <aside className={`sidebar ${open ? "open" : ""}`} aria-label="Investigation history">
        <div className="sidebar-brand">
          <div className="logo" aria-hidden="true">
            <span>AI</span>
          </div>
          <div>
            <div className="brand-name">Ops Copilot</div>
            <div className="brand-sub">Enterprise RCA Platform</div>
          </div>
        </div>

        <button className="new-investigation" onClick={onNew}>
          <span aria-hidden="true">＋</span> New Investigation
        </button>

        <div className="sidebar-search">
          <input
            type="search"
            placeholder="Search investigations…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Search investigation history"
          />
        </div>

        <div className="sidebar-section">
          <div className="sidebar-label">Recent investigations</div>
          {filtered.length === 0 ? (
            <div className="sidebar-empty">
              {history.length === 0
                ? "No investigations yet. Ask your first question below."
                : "No matches."}
            </div>
          ) : (
            <ul className="history-list">
              {filtered.map((item, index) => (
                <li key={`${item.ts}-${index}`}>
                  <button
                    className="history-item"
                    onClick={() => onSelect(item)}
                    title={item.question}
                  >
                    <span className="history-question">{item.summary || item.question}</span>
                    <span className="history-time">{formatHistoryTime(item.ts)}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="sidebar-footer">
          <span className="sidebar-footer-item">⚙ Settings</span>
          <span className="sidebar-version">v1.2.0</span>
        </div>
      </aside>
    </>
  );
}
