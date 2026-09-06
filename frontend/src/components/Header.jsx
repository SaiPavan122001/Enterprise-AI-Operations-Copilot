import { useEffect, useState } from "react";
import { checkHealth } from "../services/api";

export default function Header({ theme, onToggleTheme, onToggleSidebar }) {
  const [health, setHealth] = useState({ online: null });

  useEffect(() => {
    let cancelled = false;
    const probe = async () => {
      const result = await checkHealth();
      if (!cancelled) setHealth(result);
    };
    probe();
    const interval = setInterval(probe, 30_000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  const statusLabel =
    health.online === null
      ? "Checking…"
      : health.online
        ? "Systems operational"
        : "Backend offline";

  return (
    <header className="header">
      <button
        className="icon-btn sidebar-toggle"
        onClick={onToggleSidebar}
        aria-label="Toggle navigation"
      >
        ☰
      </button>

      <div className="header-title">
        <h1>Investigations</h1>
        <span className="header-subtitle">AI Operations Copilot</span>
      </div>

      <div className="header-actions">
        <div
          className={`status-pill ${health.online ? "ok" : health.online === false ? "down" : "unknown"}`}
          title="Backend connection status"
        >
          <span className="status-dot" aria-hidden="true" />
          {statusLabel}
        </div>

        <button
          className="icon-btn"
          onClick={onToggleTheme}
          aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
          title={theme === "dark" ? "Light mode" : "Dark mode"}
        >
          {theme === "dark" ? "☀" : "🌙"}
        </button>

        <div className="avatar" aria-label="Operator" title="Operations engineer">
          OP
        </div>
      </div>
    </header>
  );
}
