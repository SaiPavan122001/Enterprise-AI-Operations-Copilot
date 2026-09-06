import { useState } from "react";

const REASONS = [
  "Incorrect root cause",
  "Missing evidence",
  "Wrong deployment",
  "Incorrect logs",
  "Poor recommendation",
  "Other",
];

const FEEDBACK_KEY = "copilot-feedback";

function storeFeedback(entry) {
  try {
    const existing = JSON.parse(localStorage.getItem(FEEDBACK_KEY)) || [];
    existing.unshift(entry);
    localStorage.setItem(FEEDBACK_KEY, JSON.stringify(existing.slice(0, 100)));
  } catch {
    /* non-fatal */
  }
}

/**
 * Local feedback capture (no backend persistence). Asks for a reason only
 * when the user marks an investigation as not helpful.
 */
export default function Feedback({ onFeedback }) {
  const [choice, setChoice] = useState(null); // "up" | "down"
  const [showReasons, setShowReasons] = useState(false);

  const vote = (direction) => {
    setChoice(direction);
    if (direction === "down") {
      setShowReasons(true);
    } else {
      storeFeedback({ helpful: true, ts: Date.now() });
      onFeedback?.({ helpful: true });
    }
  };

  const pickReason = (reason) => {
    storeFeedback({ helpful: false, reason, ts: Date.now() });
    onFeedback?.({ helpful: false, reason });
    setShowReasons(false);
  };

  return (
    <div className="feedback-card">
      {choice === null ? (
        <>
          <span className="feedback-question">Was this investigation helpful?</span>
          <div className="feedback-actions">
            <button className="feedback-btn" onClick={() => vote("up")}>👍 Helpful</button>
            <button className="feedback-btn" onClick={() => vote("down")}>👎 Not helpful</button>
          </div>
        </>
      ) : choice === "up" ? (
        <span className="feedback-thanks">Thanks for the feedback.</span>
      ) : showReasons ? (
        <>
          <span className="feedback-question">What was wrong?</span>
          <div className="feedback-reasons">
            {REASONS.map((reason) => (
              <button key={reason} className="feedback-reason" onClick={() => pickReason(reason)}>
                {reason}
              </button>
            ))}
          </div>
        </>
      ) : (
        <span className="feedback-thanks">Thanks — your feedback was recorded.</span>
      )}
    </div>
  );
}
