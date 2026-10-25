import { STAGES } from "../services/api";

/**
 * One-line progress indicator. With the SSE stream, the label is the stage the
 * backend is actually working on (a stage is reached only after the previous one
 * reported completion); without it, a neutral "Working".
 */
export default function LoadingState({ completedStages = null }) {
  const current = completedStages ? STAGES.find((s) => !completedStages.has(s.id)) : null;
  return (
    <div className="msg assistant" aria-busy="true">
      <div className="thinking">
        <span className="pulse" aria-hidden="true" />
        <span className="thinking-text">{current ? `${current.label}…` : "Working…"}</span>
      </div>
    </div>
  );
}
