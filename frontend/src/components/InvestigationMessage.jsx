import ReactMarkdown from "react-markdown";
import RCAReport from "./RCAReport";

function formatTime(ts) {
  try {
    return new Date(ts).toLocaleTimeString(undefined, {
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return "";
  }
}

export default function InvestigationMessage({ message, onFeedback }) {
  const { role, content, ts, error, investigation, report, notice } = message;

  if (role === "user") {
    return (
      <div className="message user">
        <div className="bubble">
          <ReactMarkdown>{content}</ReactMarkdown>
        </div>
        <div className="msg-time">{formatTime(ts)}</div>
      </div>
    );
  }

  return (
    <div className={`message assistant ${error ? "error-state" : ""}`}>
      {error ? (
        <div className="error-card">
          <div className="error-card-header">
            <span className="error-icon" aria-hidden="true">!</span>
            Investigation failed
          </div>
          <p className="error-card-body">{content}</p>
        </div>
      ) : (
        <>
          {notice && (
            <div className="notice-banner" role="status">
              {notice}
            </div>
          )}
          <RCAReport
            investigation={investigation}
            report={report}
            confidence={message.confidence}
            onFeedback={onFeedback}
          />
        </>
      )}
      <div className="msg-time">{formatTime(ts)}</div>
    </div>
  );
}
