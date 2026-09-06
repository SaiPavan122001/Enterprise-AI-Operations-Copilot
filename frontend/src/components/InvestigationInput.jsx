import { useState } from "react";
import { QUESTION_MAX_LENGTH } from "../services/api";

export default function InvestigationInput({ onSubmit, disabled, autoFocus }) {
  const [value, setValue] = useState("");

  const canSubmit = !disabled && value.trim().length > 0;

  const submit = () => {
    if (!canSubmit) return;
    onSubmit(value.trim());
    setValue("");
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <div className="input-bar">
      <div className={`input-shell ${disabled ? "disabled" : ""}`}>
        <textarea
          rows={1}
          value={value}
          maxLength={QUESTION_MAX_LENGTH}
          placeholder="Ask about an incident, deployment, service, or failure…"
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={disabled}
          aria-label="Investigation question"
          autoFocus={autoFocus}
        />
        <button
          className="send-btn"
          onClick={submit}
          disabled={!canSubmit}
          aria-label="Send investigation"
        >
          <span aria-hidden="true">➜</span>
        </button>
      </div>
      <div className="input-meta">
        <span>Enter to submit · Shift+Enter for a new line</span>
        <span className={value.length >= QUESTION_MAX_LENGTH ? "limit-hit" : ""}>
          {value.length}/{QUESTION_MAX_LENGTH}
        </span>
      </div>
    </div>
  );
}
