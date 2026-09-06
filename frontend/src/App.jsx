import { useCallback, useEffect, useRef, useState } from "react";

import Header from "./components/Header";
import Sidebar from "./components/Sidebar";
import InvestigationInput from "./components/InvestigationInput";
import InvestigationMessage from "./components/InvestigationMessage";
import LoadingState from "./components/LoadingState";
import { investigateStream, investigate } from "./services/api";
import "./App.css";

const THEME_KEY = "copilot-theme";
const HISTORY_KEY = "copilot-history";
const MAX_HISTORY = 20;

const EXAMPLES = [
  { title: "Payroll failure", question: "Why is payroll failing?" },
  {
    title: "Payment service incident",
    question: "Investigate the latest payment-service incident",
  },
  {
    title: "Deployment correlation",
    question: "Was the recent deployment responsible for the outage?",
  },
  { title: "Authentication failures", question: "Analyze authentication failures" },
];

function loadHistory() {
  try {
    const parsed = JSON.parse(localStorage.getItem(HISTORY_KEY));
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function App() {
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(false);
  const [completedStages, setCompletedStages] = useState(null); // Set of backend-confirmed stage ids
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [history, setHistory] = useState(loadHistory);
  const [theme, setTheme] = useState(() => {
    const stored = localStorage.getItem(THEME_KEY);
    return stored === "light" || stored === "dark" ? stored : "dark";
  });

  const bottomRef = useRef(null);
  const loadingRef = useRef(false);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, loading]);

  const pushHistory = useCallback((question, result, ts) => {
    setHistory((prev) => {
      const investigation = result?.investigation;
      const entry = {
        question,
        ts,
        summary: investigation?.summary || null,
        confidence: investigation?.confidence || null,
        result, // full result stored so history click restores it locally
      };
      const next = [
        entry,
        ...prev.filter(
          (item) => item.question.toLowerCase() !== question.toLowerCase()
        ),
      ].slice(0, MAX_HISTORY);
      try {
        localStorage.setItem(HISTORY_KEY, JSON.stringify(next));
      } catch {
        // Storage quota exceeded: persist metadata only.
        try {
          localStorage.setItem(
            HISTORY_KEY,
            JSON.stringify(next.map(({ result: _r, ...rest }) => rest))
          );
        } catch {
          /* ignore */
        }
      }
      return next;
    });
  }, []);

  const runInvestigation = useCallback(
    async (question) => {
      if (!question || loadingRef.current) return;
      loadingRef.current = true;
      setSidebarOpen(false);
      setCompletedStages(new Set());

      const ts = Date.now();
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
        } catch (streamErr) {
          if (!loadingRef.current) return; // superseded by New Investigation
          result = await investigate(question); // graceful fallback
        }

        if (!loadingRef.current) return;

        setMessages((prev) => [
          ...prev,
          {
            role: "assistant",
            investigation: result.investigation || null,
            report: result.report || null,
            confidence: result.investigation?.confidence || null,
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

  const startNewInvestigation = () => {
    loadingRef.current = false;
    setMessages([]);
    setLoading(false);
    setCompletedStages(null);
    setSidebarOpen(false);
  };

  /** Restore a previous investigation from localStorage history. */
  const selectHistory = (item) => {
    setSidebarOpen(false);
    if (loadingRef.current) return;
    if (item.result) {
      setMessages([
        { role: "user", content: item.question, ts: item.ts },
        {
          role: "assistant",
          investigation: item.result.investigation || null,
          report: item.result.report || null,
          confidence: item.result.investigation?.confidence || null,
          notice: item.result.message || null,
          error: false,
          ts: item.ts,
        },
      ]);
      return;
    }
    runInvestigation(item.question); // metadata-only entry: re-run
  };

  return (
    <div className="app-shell">
      <Sidebar
        history={history}
        onSelect={selectHistory}
        onNew={startNewInvestigation}
        open={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
      />

      <div className="main-area">
        <Header
          theme={theme}
          onToggleTheme={() => {
            const next = theme === "dark" ? "light" : "dark";
            setTheme(next);
            localStorage.setItem(THEME_KEY, next);
          }}
          onToggleSidebar={() => setSidebarOpen((v) => !v)}
        />

        {messages.length === 0 && !loading ? (
          <div className="welcome">
            <div className="welcome-inner">
              <div className="welcome-badge">AI Operations Copilot</div>
              <h1>Investigate incidents with grounded evidence.</h1>
              <p>
                Correlate incidents, deployments, logs and runbooks to generate
                structured root-cause reports â€” with supporting evidence always
                inspectable and confidence grounded in evidence strength.
              </p>

              <div className="example-grid">
                {EXAMPLES.map((example) => (
                  <button
                    key={example.title}
                    className="example-card"
                    onClick={() => runInvestigation(example.question)}
                  >
                    <span className="example-title">{example.title}</span>
                    <span className="example-question">{example.question}</span>
                    <span className="example-cta">Run investigation âžœ</span>
                  </button>
                ))}
              </div>
            </div>
          </div>
        ) : (
          <div className="chat-window">
            {messages.map((message, index) => (
              <InvestigationMessage key={index} message={message} onFeedback={() => {}} />
            ))}
            {loading && <LoadingState completedStages={completedStages} />}
            <div ref={bottomRef} />
          </div>
        )}

        <InvestigationInput onSubmit={runInvestigation} disabled={loading} />
      </div>
    </div>
  );
}

export default App;
