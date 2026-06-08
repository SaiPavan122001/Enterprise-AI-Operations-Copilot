import { useState, useRef, useEffect } from "react";
import ReactMarkdown from "react-markdown";
import "./App.css";

function App() {
  const [messages, setMessages] = useState([]);
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [darkMode, setDarkMode] = useState(true);

  const bottomRef = useRef();

  useEffect(() => {
    bottomRef.current?.scrollIntoView({
      behavior: "smooth",
    });
  }, [messages, loading]);

  useEffect(() => {
    document.body.className = darkMode ? "dark" : "light";
  }, [darkMode]);

  const sendMessage = async (text = question) => {
    if (!text.trim()) return;

    const userMessage = {
      role: "user",
      content: text,
    };

    setMessages((prev) => [...prev, userMessage]);
    setQuestion("");
    setLoading(true);

    try {
      const response = await fetch(
        `http://127.0.0.1:8000/investigate?question=${encodeURIComponent(
          text
        )}`,
        {
          method: "POST",
        }
      );

      const data = await response.json();

      const aiMessage = {
        role: "assistant",
        content: data.report,
      };

      setMessages((prev) => [...prev, aiMessage]);
    } catch (error) {
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: "❌ Failed to connect to backend.",
        },
      ]);
    }

    setLoading(false);
  };

  const suggestions = [
    "Why is payroll failing?",
    "Investigate 500 API errors",
    "Analyze deployment issues",
    "Find root cause of database outage",
  ];

  return (
    <div className="app">

      <div className="header">
        <div>
          <h2>Enterprise AI Operations Copilot</h2>
          <p>LangGraph • Gemini • Qdrant • FastAPI</p>
        </div>

        <button
          className="theme-toggle"
          onClick={() => setDarkMode(!darkMode)}
        >
          {darkMode ? "☀" : "🌙"}
        </button>
      </div>

      {messages.length === 0 ? (
        <div className="hero">

          <h1>What would you like to investigate?</h1>

          <div className="hero-input">

            <input
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="Ask an RCA question..."
            />

            <button onClick={() => sendMessage()}>
              ➜
            </button>

          </div>

          <div className="suggestions">
            {suggestions.map((item, index) => (
              <button
                key={index}
                onClick={() => sendMessage(item)}
              >
                {item}
              </button>
            ))}
          </div>

        </div>
      ) : (
        <>
          <div className="chat-window">

            {messages.map((message, index) => (
              <div
                key={index}
                className={
                  message.role === "user"
                    ? "message user"
                    : "message assistant"
                }
              >
                <ReactMarkdown>
                  {message.content}
                </ReactMarkdown>
              </div>
            ))}

            {loading && (
              <div className="message assistant">
                <div className="typing">
                  <span></span>
                  <span></span>
                  <span></span>
                </div>
              </div>
            )}

            <div ref={bottomRef}></div>

          </div>

          <div className="chat-input">

            <input
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="Ask another investigation..."
              onKeyDown={(e) =>
                e.key === "Enter" && sendMessage()
              }
            />

            <button onClick={() => sendMessage()}>
              Send
            </button>

          </div>
        </>
      )}
    </div>
  );
}

export default App;