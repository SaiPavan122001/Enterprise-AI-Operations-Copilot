import ReactMarkdown from "react-markdown";
import EvidencePanel from "./EvidencePanel";
import Timeline from "./Timeline";
import Feedback from "./Feedback";

function ConfidenceBadge({ level, strength }) {
  const display = level || strength;
  if (!display) return null;
  const normalized = display.toLowerCase();
  const cls = ["high", "medium", "low", "insufficient"].includes(normalized)
    ? normalized
    : "medium";
  return (
    <span className={`confidence-badge ${cls}`}>
      <span className="confidence-dot" aria-hidden="true" />
      Confidence: {display}
    </span>
  );
}

function SectionCard({ label, kind, children }) {
  return (
    <div className={`rca-section ${kind ? `rca-${kind}` : ""}`}>
      {label && (
        <h3 className="rca-section-title">
          <span className={`kind-tag kind-${(kind || "analysis").replace("_", "-")}`}>
            {kind === "observed" ? "OBSERVED EVIDENCE" : kind === "recommendation" ? "RECOMMENDATION" : "AI ANALYSIS"}
          </span>
          {label}
        </h3>
      )}
      <div className="rca-section-body">{children}</div>
    </div>
  );
}

function ListSection({ items, ordered }) {
  if (!items || items.length === 0) return <p>None identified.</p>;
  const Tag = ordered ? "ol" : "ul";
  return (
    <Tag>
      {items.map((item, index) => (
        <li key={index}>{item}</li>
      ))}
    </Tag>
  );
}

function Markdown({ text }) {
  return <ReactMarkdown>{text || "_Not available._"}</ReactMarkdown>;
}

/**
 * Renders the structured InvestigationResult returned by the backend.
 * Falls back to plain markdown rendering when structured data is absent.
 */
export default function RCAReport({ investigation, report, confidence, onFeedback }) {
  if (!investigation) {
    // Legacy fallback: plain markdown report.
    return (
      <div className="rca-report">
        <div className="rca-header">
          <h2 className="rca-title">
            <span className="rca-title-mark" aria-hidden="true" />
            Root Cause Analysis
          </h2>
          <ConfidenceBadge level={confidence} />
        </div>
        <div className="rca-section">
          <div className="rca-section-body">
            <ReactMarkdown>{report}</ReactMarkdown>
          </div>
        </div>
      </div>
    );
  }

  const {
    summary,
    impact,
    root_cause: rootCause,
    confidence: resultConfidence,
    evidence_strength: evidenceStrength,
    contributing_factors: contributingFactors,
    recommended_remediation: remediation,
    preventive_actions: preventiveActions,
    observed_evidence: observedEvidence,
    investigation_details: investigationDetails,
    timeline,
    evidence,
    validation,
  } = investigation;

  return (
    <div className="rca-report">
      <div className="rca-header">
        <h2 className="rca-title">
          <span className="rca-title-mark" aria-hidden="true" />
          Root Cause Analysis
        </h2>
        <div className="rca-badges">
          <ConfidenceBadge level={resultConfidence} />
          <span className={`strength-pill strength-${evidenceStrength?.toLowerCase()}`}>
            Evidence: {evidenceStrength}
          </span>
        </div>
      </div>

      {validation?.notes?.length > 0 && (
        <div className="validation-notes" role="note">
          {validation.notes.map((note, index) => (
            <div key={index} className="validation-note">⚠ {note}</div>
          ))}
        </div>
      )}

      <SectionCard label="Summary" kind="analysis">
        <Markdown text={summary} />
      </SectionCard>

      <SectionCard label="Impact" kind="analysis">
        <Markdown text={impact} />
      </SectionCard>

      {timeline && timeline.length > 0 && (
        <SectionCard label="Timeline" kind="observed">
          <Timeline events={timeline} />
        </SectionCard>
      )}

      <SectionCard label="Root Cause" kind="analysis">
        <Markdown text={rootCause} />
      </SectionCard>

      <SectionCard label="Contributing Factors" kind="analysis">
        <ListSection items={contributingFactors} />
      </SectionCard>

      <SectionCard label="Recommended Remediation" kind="recommendation">
        <ListSection items={remediation} ordered />
      </SectionCard>

      <SectionCard label="Preventive Actions" kind="recommendation">
        <ListSection items={preventiveActions} ordered />
      </SectionCard>

      {investigationDetails && (
        <SectionCard label="Investigation Details" kind="analysis">
          <Markdown text={investigationDetails} />
        </SectionCard>
      )}

      <EvidencePanel evidence={evidence} observedEvidence={observedEvidence} />

      {onFeedback && <Feedback onFeedback={onFeedback} />}
    </div>
  );
}
