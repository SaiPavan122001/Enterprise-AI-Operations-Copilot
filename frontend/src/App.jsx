import { useCallback, useEffect, useRef, useState } from "react";

import Header from "./components/Header";
import Sidebar from "./components/Sidebar";
import InvestigationInput from "./components/InvestigationInput";
import InvestigationMessage from "./components/InvestigationMessage";
import LoadingState from "./components/LoadingState";
import Login from "./components/Login";
import ActionsPanel from "./components/ActionsPanel";
import { investigateStream, investigate, logout, me, setUnauthorizedHandler } from "./services/api";
import "./App.css";

const THEME_KEY = "copilot-theme";
const SIDEBAR_KEY = "copilot-sidebar";
// History is per user and holds METADATA only (server-redacted question, time,
// status) - answers are never written to browser storage; they stay in page memory.
const LEGACY_HISTORY_KEY = "copilot-history";
const historyKey = (user) => `copilot-history:${user}`;
const MAX_HISTORY = 20;

function readStorage(key) {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeStorage(key, value) {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch {
    /* storage unavailable: keep the setting in memory */
  }
}

function loadHistory(user) {
  try {
    localStorage.removeItem(LEGACY_HISTORY_KEY); // older versions stored full answers
    const parsed = JSON.parse(localStorage.getItem(historyKey(user)));
    return Array.isArray(parsed) ? parsed.map(({ question, ts, status }) => ({ question, ts, status })) : [];
  } catch {
    return [];
  }
}

function initialTheme() {
  const stored = readStorage(THEME_KEY);
  if (stored === "light" || stored === "dark") return stored;
  return window.matchMedia?.("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

function App() {
  const [identity, setIdentity] = useState(undefined); // undefined = checking, null = signed out
  const [showActions, setShowActions] = useState(false);
  const resultsRef = useRef(new Map()); // ts -> result, in memory only
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(false);
  const [completedStages, setCompletedStages] = useState(null); // Set of backend-confirmed stage ids
  const [mobileSidebar, setMobileSidebar] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => readStorage(SIDEBAR_KEY) === "collapsed");
  const [history, setHistory] = useState([]);
  const [activeTs, setActiveTs] = useState(null);
  const [theme, setTheme] = useState(initialTheme);

  const bottomRef = useRef(null);
  const loadingRef = useRef(false);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  useEffect(() => {
    setUnauthorizedHandler(() => setIdentity(null));
    me().then((who) => setIdentity(who || null));
  }, []);

  useEffect(() => {
    setHistory(identity ? loadHistory(identity.user) : []);
    resultsRef.current = new Map();
  }, [identity]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, loading]);

  const pushHistory = useCallback((question, result, ts) => {
    if (!identity) return;
    resultsRef.current.set(ts, result);
    setHistory((prev) => {
      // The server returns the question with personal data redacted; store that.
      const safeQuestion = result?.investigation?.question || question;
      const entry = { question: safeQuestion, ts, status: result?.investigation?.answer_status || null };
      const next = [
        entry,
        ...prev.filter((item) => item.question.toLowerCase() !== safeQuestion.toLowerCase()),
      ].slice(0, MAX_HISTORY);
      writeStorage(historyKey(identity.user), JSON.stringify(next));
      return next;
    });
  }, [identity]);

  const runInvestigation = useCallback(
    async (question) => {
      if (!question || loadingRef.current) return;
      loadingRef.current = true;
      setMobileSidebar(false);
      setCompletedStages(new Set());

      const ts = Date.now();
      setActiveTs(ts);
      setMessages((prev) => [...prev, { role: "user", content: question, ts }]);
      setLoading(true);

      try {
        // Prefer the streaming endpoint: REAL workflow progress via SSE.
        let result;
        try {
          result = await investigateStream(question, (event) => {
            if (event.type === "stage_completed") {
              setCompletedStages((prev) => {
                const next = new Set(prev || []);
                next.add(event.stage);
                return next;
              });
            }
          });
        } catch {
          if (!loadingRef.current) return; // superseded by New chat
          result = await investigate(question); // graceful fallback
        }

        if (!loadingRef.current) return;

        setMessages((prev) => [
          ...prev,
          {
            role: "assistant",
            investigation: result.investigation || null,
            report: result.report || null,
            notice: result.message || null,
            error: false,
            ts: Date.now(),
          },
        ]);
        pushHistory(question, result, ts);
      } catch (err) {
        if (!loadingRef.current) return;
        setMessages((prev) => [
          ...prev,
          {
            role: "assistant",
            content: err.message || "Something went wrong. Please try again.",
            error: true,
            ts: Date.now(),
          },
        ]);
      } finally {
        setLoading(false);
        loadingRef.current = false;
        setCompletedStages(null);
      }
    },
    [pushHistory]
  );

  const startNewChat = () => {
    loadingRef.current = false;
    setMessages([]);
    setLoading(false);
    setCompletedStages(null);
    setMobileSidebar(false);
    setActiveTs(null);
  };

  /** Restore a previous investigation (answer from page memory, else re-run). */
  const selectHistory = (item) => {
    setMobileSidebar(false);
    if (loadingRef.current) return;
    const result = resultsRef.current.get(item.ts);
    if (result) {
      setActiveTs(item.ts);
      setMessages([
        { role: "user", content: item.question, ts: item.ts },
        {
          role: "assistant",
          investigation: result.investigation || null,
          report: result.report || null,
          notice: result.message || null,
          error: false,
          ts: item.ts,
        },
      ]);
      return;
    }
    setMessages([]);
    runInvestigation(item.question); // answers are not stored: re-run
  };

  const toggleTheme = () => {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    writeStorage(THEME_KEY, next);
  };

  const toggleSidebar = () => {
    if (window.matchMedia?.("(max-width: 860px)").matches) {
      setMobileSidebar((v) => !v);
      return;
    }
    setSidebarCollapsed((v) => {
      writeStorage(SIDEBAR_KEY, v ? null : "collapsed");
      return !v;
    });
  };

  const signOut = async () => {
    try {
      await logout();
    } catch {
      /* already signed out */
    }
    if (identity) writeStorage(historyKey(identity.user), null);
    startNewChat();
    setShowActions(false);
    setIdentity(null);
  };

  if (identity === undefined) {
    return <div className="boot-screen"><span className="spinner" aria-label="Loading" /></div>;
  }
  if (identity === null) {
    return <Login onSignedIn={setIdentity} theme={theme} onToggleTheme={toggleTheme} />;
  }

  const empty = messages.length === 0 && !loading;

  return (
    <div className={`app-shell ${sidebarCollapsed ? "sidebar-collapsed" : ""}`}>
      <Sidebar
        history={history}
        activeTs={activeTs}
        onSelect={selectHistory}
        onNew={startNewChat}
        open={mobileSidebar}
        onClose={() => setMobileSidebar(false)}
        onCollapse={toggleSidebar}
        identity={identity}
        onOpenTools={() => { setShowActions(true); setMobileSidebar(false); }}
        onSignOut={signOut}
      />

      <main className="main">
        <Header
          theme={theme}
          onToggleTheme={toggleTheme}
          onToggleSidebar={toggleSidebar}
          sidebarCollapsed={sidebarCollapsed}
          onNew={startNewChat}
        />

        {empty ? (
          <div className="empty-state">
            <h1 className="empty-title">What would you like to investigate?</h1>
            <InvestigationInput onSubmit={runInvestigation} disabled={loading} autoFocus />
          </div>
        ) : (
          <>
            <div className="thread" aria-live="polite">
              <div className="thread-inner">
                {messages.map((message, index) => (
                  <InvestigationMessage key={`${message.ts}-${index}`} message={message} />
                ))}
                {loading && <LoadingState completedStages={completedStages} />}
                <div ref={bottomRef} className="thread-end" />
              </div>
            </div>
            <div className="composer-dock">
              <InvestigationInput onSubmit={runInvestigation} disabled={loading} autoFocus />
            </div>
          </>
        )}
      </main>

      {showActions && <ActionsPanel identity={identity} onClose={() => setShowActions(false)} />}
    </div>
  );
}

export default App;
