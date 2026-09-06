import { STAGES } from "../services/api";

/**
 * Investigation loading state.
 * When `completedStages` is provided (from the real SSE stream), each stage
 * shows its ACTUAL backend-reported status. When streaming is unavailable,
 * it falls back to an honest indeterminate state - no fake checkmarks.
 */

export default function LoadingState({ completedStages = null }) {
  const streaming = completedStages !== null;

  return (
    <div className="message assistant loading-message" aria-live="polite" aria-busy="true">
      <div className="loading-header">
        <span className="spinner" aria-hidden="true" />
        <span>Investigating incident…</span>
      </div>

      <ul className="loading-stages">
        {STAGES.map((stage) => {
          const done = streaming && completedStages.has(stage.id);
          const active =
            streaming &&
            !done &&
            stage.id === STAGES.find((s) => !completedStages.has(s.id))?.id;
          return (
            <li
              key={stage.id}
              className={done ? "done" : active ? "active" : ""}
            >
              <span className="stage-icon" aria-hidden="true">
                {done ? "✓" : active ? "●" : "○"}
              </span>
              {stage.label}
            </li>
          );
        })}
      </ul>

      <p className="loading-note">
        {streaming
          ? "Live pipeline progress — stages are marked complete only after the backend finishes them."
          : "Running the multi-agent RCA pipeline — this can take up to a minute."}
      </p>
    </div>
  );
}
