import { useEffect, useRef, useState } from "react";
import { LogoutIcon, PanelIcon, PenIcon, ToolIcon } from "./Icons";

function bucket(ts) {
  const date = new Date(ts);
  const now = new Date();
  if (date.toDateString() === now.toDateString()) return "Today";
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (date.toDateString() === yesterday.toDateString()) return "Yesterday";
  return now - date < 7 * 864e5 ? "Previous 7 days" : "Older";
}

function AccountMenu({ identity, onOpenTools, onSignOut }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    const close = (e) => {
      if (!ref.current?.contains(e.target)) setOpen(false);
    };
    const esc = (e) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);

  return (
    <div className="account" ref={ref}>
      {open && (
        <div className="menu" role="menu">
          <div className="menu-meta">
            Tenant <b>{identity.tenant}</b> · {identity.services.length} services
          </div>
          <button role="menuitem" className="menu-item" onClick={() => { setOpen(false); onOpenTools(); }}>
            <ToolIcon size={18} /> Tools &amp; approvals
          </button>
          <button role="menuitem" className="menu-item" onClick={() => { setOpen(false); onSignOut(); }}>
            <LogoutIcon size={18} /> Sign out
          </button>
        </div>
      )}
      <button className="account-btn" onClick={() => setOpen((v) => !v)} aria-haspopup="menu" aria-expanded={open}>
        <span className="avatar">{identity.user.slice(0, 1).toUpperCase()}</span>
        <span className="account-text">
          <span className="account-name">{identity.user}</span>
          <span className="account-role">{identity.role}</span>
        </span>
      </button>
    </div>
  );
}

export default function Sidebar({
  history, activeTs, onSelect, onNew, open, onClose, onCollapse, identity, onOpenTools, onSignOut,
}) {
  const groups = [];
  for (const item of history) {
    const label = bucket(item.ts);
    const group = groups.find((g) => g.label === label);
    if (group) group.items.push(item);
    else groups.push({ label, items: [item] });
  }

  return (
    <>
      <div className={`scrim ${open ? "visible" : ""}`} onClick={onClose} aria-hidden="true" />
      <aside className={`sidebar ${open ? "open" : ""}`} aria-label="Chat history">
        <div className="sidebar-top">
          <button className="icon-btn" onClick={onCollapse} aria-label="Close sidebar" title="Close sidebar">
            <PanelIcon />
          </button>
          <button className="icon-btn" onClick={onNew} aria-label="New chat" title="New chat">
            <PenIcon />
          </button>
        </div>

        <button className="new-chat" onClick={onNew}>
          <span className="new-chat-mark" aria-hidden="true">O</span>
          Ops Copilot
        </button>

        <nav className="history">
          {history.length === 0 && <p className="history-empty">Your investigations will appear here.</p>}
          {groups.map((group) => (
            <div key={group.label} className="history-group">
              <div className="history-label">{group.label}</div>
              {group.items.map((item) => (
                <button
                  key={item.ts}
                  className={`history-item ${item.ts === activeTs ? "active" : ""}`}
                  onClick={() => onSelect(item)}
                  title={item.question}
                >
                  {item.question}
                </button>
              ))}
            </div>
          ))}
        </nav>

        <AccountMenu identity={identity} onOpenTools={onOpenTools} onSignOut={onSignOut} />
      </aside>
    </>
  );
}
