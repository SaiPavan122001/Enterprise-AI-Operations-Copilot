import { useLayoutEffect, useRef, useState } from "react";
import { QUESTION_MAX_LENGTH } from "../services/api";
import { ArrowUpIcon } from "./Icons";

export default function InvestigationInput({ onSubmit, disabled, autoFocus }) {
  const [value, setValue] = useState("");
  const ref = useRef(null);
  const canSubmit = !disabled && value.trim().length > 0;
  const nearLimit = value.length > QUESTION_MAX_LENGTH * 0.8;

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [value]);

  const submit = () => {
    if (!canSubmit) return;
    onSubmit(value.trim());
    setValue("");
  };

  return (
    <div className="composer-wrap">
      <form
        className={`composer ${disabled ? "busy" : ""}`}
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <textarea
          ref={ref}
          rows={1}
          value={value}
          maxLength={QUESTION_MAX_LENGTH}
          placeholder="Ask about an incident, a service or a deployment"
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              submit();
            }
          }}
          aria-label="Message"
          autoFocus={autoFocus}
        />
        <button className="send" type="submit" disabled={!canSubmit} aria-label="Send">
          <ArrowUpIcon size={18} />
        </button>
      </form>
      <p className="composer-note">
        {nearLimit
          ? `${value.length}/${QUESTION_MAX_LENGTH} characters`
          : "Answers come only from your organisation's incident records. Check important conclusions."}
      </p>
    </div>
  );
}
