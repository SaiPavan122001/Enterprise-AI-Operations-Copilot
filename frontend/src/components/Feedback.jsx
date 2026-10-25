import { useState } from "react";
import { ThumbDownIcon, ThumbUpIcon } from "./Icons";

const REASONS = ["Incorrect root cause", "Missing evidence", "Wrong deployment", "Not what I asked", "Other"];
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

/** Thumbs up / down, kept in this browser only (no backend persistence). */
export default function Feedback() {
  const [choice, setChoice] = useState(null); // "up" | "down" | "sent"

  const vote = (helpful) => {
    if (helpful) storeFeedback({ helpful: true, ts: Date.now() });
    setChoice(helpful ? "up" : "down");
  };

  return (
    <>
      <button className={`icon-btn small ${choice === "up" ? "on" : ""}`} onClick={() => vote(true)}
        aria-label="Good answer" title="Good answer" disabled={choice !== null}>
        <ThumbUpIcon size={16} />
      </button>
      <button className={`icon-btn small ${choice === "down" || choice === "sent" ? "on" : ""}`}
        onClick={() => vote(false)} aria-label="Bad answer" title="Bad answer" disabled={choice !== null}>
        <ThumbDownIcon size={16} />
      </button>
      {choice === "down" && (
        <span className="reasons">
          {REASONS.map((reason) => (
            <button key={reason} className="chip" onClick={() => {
              storeFeedback({ helpful: false, reason, ts: Date.now() });
              setChoice("sent");
            }}>
              {reason}
            </button>
          ))}
        </span>
      )}
      {choice === "sent" && <span className="muted small">Thanks for the feedback.</span>}
    </>
  );
}
