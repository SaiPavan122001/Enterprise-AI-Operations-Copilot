import { useEffect, useState } from "react";
import { checkHealth } from "../services/api";
import { MoonIcon, PanelIcon, PenIcon, SunIcon } from "./Icons";

export default function Header({ theme, onToggleTheme, onToggleSidebar, sidebarCollapsed, onNew }) {
  const [online, setOnline] = useState(null);

  useEffect(() => {
    let cancelled = false;
    const probe = async () => {
      const result = await checkHealth();
      if (!cancelled) setOnline(result.online);
    };
    probe();
    const interval = setInterval(probe, 30_000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  return (
    <header className="topbar">
      <div className="topbar-left">
        <button className={`icon-btn sidebar-open ${sidebarCollapsed ? "show" : ""}`} onClick={onToggleSidebar}
          aria-label="Open sidebar" title="Open sidebar">
          <PanelIcon />
        </button>
        {sidebarCollapsed && (
          <button className="icon-btn hide-mobile" onClick={onNew} aria-label="New chat" title="New chat">
            <PenIcon />
          </button>
        )}
        <span className="brand">Ops Copilot</span>
        {online === false && <span className="offline" role="status">Backend offline</span>}
      </div>
      <button
        className="icon-btn"
        onClick={onToggleTheme}
        aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
        title={theme === "dark" ? "Light mode" : "Dark mode"}
      >
        {theme === "dark" ? <SunIcon /> : <MoonIcon />}
      </button>
    </header>
  );
}
