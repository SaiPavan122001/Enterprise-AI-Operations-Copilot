import { useMemo, useState } from "react";

function relevanceLabel(score) {
  if (score == null) return null;
  if (score >= 0.55) return "High";
  if (score >= 0.4) return "Medium";
  return "Low";
}

function Accordion({ title, badge, children, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className={`evidence-card ${open ? "open" : ""}`}>
      <button
        className="evidence-toggle"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <span className="evidence-title">{title}</span>
        {badge != null && <span className="evidence-badge">{badge}</span>}
        <span className="chevron" aria-hidden="true">{open ? "â–¾" : "â–¸"}</span>
      </button>
      {open && <div className="evidence-content">{children}</div>}
    </div>
  );
}

function IncidentEvidence({ incidents }) {
  return (
    <ul className="incident-list">
      {incidents.map((incident) => (
        <li key={incident.incident_id} className="incident-row">
          <div className="incident-top">
            <span className="mono id">{incident.incident_id}</span>
            {incident.severity && (
              <span className={`severity-badge ${(incident.severity || "").toLowerCase()}`}>
                {incident.severity}
              </span>
            )}
            {incident.status && <span className="pill">{incident.status}</span>}
            {incident.relevance_score != null && (
              <span className="pill relevance">
                Relevance: {relevanceLabel(incident.relevance_score)}
                {` (${incident.relevance_score.toFixed(2)})`}
              </span>
            )}
          </div>
          {incident.title && <div className="incident-title">{incident.title}</div>}
          <div className="incident-meta">
            {[
              incident.service,
              incident.root_cause ? `Known cause: ${incident.root_cause}` : null,
              incident.deployment_id ? `Related deployment: ${incident.deployment_id}` : null,
            ].filter(Boolean).join(" Â· ")}
          </div>
        </li>
      ))}
    </ul>
  );
}

function DeploymentEvidence({ deployments }) {
  return (
    <ul className="deployment-list">
      {deployments.map((deployment) => (
        <li key={deployment.deployment_id} className="deployment-row">
          <span className="mono id">{deployment.deployment_id}</span>
          <div className="deployment-main">
            {deployment.change && <div className="deployment-change">{deployment.change}</div>}
            <div className="deployment-meta">
              {[deployment.service, deployment.time].filter(Boolean).join(" Â· ")}
            </div>
          </div>
        </li>
      ))}
    </ul>
  );
}

function LogEvidence({ logs }) {
  const text = useMemo(
    () =>
      logs
        .map((entry) =>
          [entry.timestamp, entry.service, entry.level, entry.message]
            .filter(Boolean)
            .join(" ")
        )
        .join("\n"),
    [logs]
  );

  const copy = () => {
    navigator.clipboard?.writeText(text).catch(() => {});
  };

  return (
    <div className="log-evidence">
      <div className="log-toolbar">
        <span className="log-count">{logs.length} relevant lines (errors first)</span>
        <button className="log-copy" onClick={copy} aria-label="Copy log lines">
          â§‰ Copy
        </button>
      </div>
      <div className="log-viewer" role="log" aria-label="Relevant log entries">
        {logs.map((entry, index) => (
          <div key={index} className={`log-line ${(entry.level || "").toLowerCase()}`}>
            <span className="log-num">{String(index + 1).padStart(3, "0")}</span>
            <span className="log-text">
              {[entry.timestamp, entry.service, entry.level, entry.message]
                .filter(Boolean)
                .join(" ")}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function RunbookEvidence({ runbook }) {
  if (!runbook) return null;
  return (
    <div className="runbook-card">
      <div className="runbook-header">
        <span className="runbook-badge">Runbook Guidance</span>
        <span className="runbook-name">{runbook.title || runbook.name}</span>
      </div>
      <pre className="runbook-content">{runbook.content}</pre>
      <p className="runbook-note">
        Source: {runbook.name}. Runbooks are internal operational documentation
        used as guidance â€” they are not observed incident evidence.
      </p>
    </div>
  );
}

/**
 * Explainable evidence panel. Renders only data actually retrieved by the
 * backend. Observed evidence is labeled distinctly from runbook guidance.
 */
export default function EvidencePanel({ evidence, observedEvidence }) {
  if (!evidence) return null;
  const incidents = evidence.incident_evidence || [];
  const deployments = evidence.deployment_evidence || [];
  const logs = evidence.log_evidence || [];
  const runbook = evidence.runbook_evidence;

  const hasAny = incidents.length || deployments.length || logs.length || runbook;

  if (!hasAny) {
    return (
      <div className="evidence-panel">
        <div className="evidence-panel-header">
          <h4>Supporting Evidence</h4>
          <span className="evidence-panel-sub">
            No evidence was retrieved for this question
          </span>
        </div>
        <div className="evidence-empty">
          No relevant incidents, deployments, logs or runbooks matched this
          question. Treat any conclusions accordingly.
        </div>
      </div>
    );
  }

  return (
    <div className="evidence-panel">
      <div className="evidence-panel-header">
        <h4>Supporting Evidence</h4>
        <span className="evidence-panel-sub">
          Inspect the retrieved data behind this analysis
        </span>
      </div>

      {incidents.length > 0 && (
        <Accordion title="Incident Evidence" badge={`${incidents.length} matched`} defaultOpen>
          <span className="evidence-source-tag">OBSERVED EVIDENCE</span>
          <IncidentEvidence incidents={incidents} />
        </Accordion>
      )}

      {deployments.length > 0 && (
        <Accordion title="Deployment Evidence" badge={`${deployments.length} correlated`}>
          <span className="evidence-source-tag">OBSERVED EVIDENCE</span>
          <DeploymentEvidence deployments={deployments} />
        </Accordion>
      )}

      {logs.length > 0 && (
        <Accordion title="Log Evidence" badge={`${logs.length} lines`}>
          <span className="evidence-source-tag">OBSERVED EVIDENCE</span>
          <LogEvidence logs={logs} />
        </Accordion>
      )}

      {runbook && (
        <Accordion title="Runbook Evidence" badge="guidance">
          <span className="evidence-source-tag guidance">RUNBOOK GUIDANCE</span>
          <RunbookEvidence runbook={runbook} />
        </Accordion>
      )}

      {observedEvidence && observedEvidence.length > 0 && (
        <Accordion title="AI-Cited Evidence" badge={`${observedEvidence.length} facts`}>
          <span className="evidence-source-tag">AI ANALYSIS</span>
          <ul className="cited-facts">
            {observedEvidence.map((fact, index) => (
              <li key={index}>{fact}</li>
            ))}
          </ul>
        </Accordion>
      )}
    </div>
  );
}

