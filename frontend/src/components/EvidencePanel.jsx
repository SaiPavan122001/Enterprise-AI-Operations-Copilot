import Timeline from "./Timeline";
import { ChevronIcon } from "./Icons";

const join = (parts) => parts.filter(Boolean).join(" · ");

/**
 * "Sources" disclosure: only data the backend actually retrieved. Records are
 * observed evidence; runbooks are guidance, not evidence that something happened.
 */
export default function EvidencePanel({ investigation }) {
  const evidence = investigation?.evidence;
  if (!evidence) return null;
  const incidents = evidence.incident_evidence || [];
  const deployments = evidence.deployment_evidence || [];
  const logs = evidence.log_evidence || [];
  const runbook = evidence.runbook_evidence;
  const timeline = investigation.timeline || [];
  const cited = investigation.observed_evidence || [];
  const count = incidents.length + deployments.length + logs.length + (runbook ? 1 : 0);
  if (count === 0) return null;

  return (
    <details className="sources">
      <summary>
        <ChevronIcon size={14} className="sources-chevron" />
        {count} source{count === 1 ? "" : "s"}
        <span className="sources-kinds">
          {join([
            incidents.length && `${incidents.length} incident${incidents.length === 1 ? "" : "s"}`,
            deployments.length && `${deployments.length} deployment${deployments.length === 1 ? "" : "s"}`,
            logs.length && `${logs.length} log line${logs.length === 1 ? "" : "s"}`,
            runbook && "runbook",
          ])}
        </span>
      </summary>

      <div className="sources-body">
        {incidents.length > 0 && (
          <section>
            <h5>Incidents</h5>
            <ul className="source-list">
              {incidents.map((i) => (
                <li key={i.incident_id}>
                  <div className="source-head">
                    <code>{i.incident_id}</code>
                    <span className="source-title">{i.title}</span>
                    {i.severity && <span className={`sev sev-${i.severity.toLowerCase()}`}>{i.severity}</span>}
                  </div>
                  <div className="source-meta">
                    {join([i.service, i.status, i.root_cause && `Recorded cause: ${i.root_cause}`,
                      i.deployment_id && `Deployment ${i.deployment_id}`])}
                  </div>
                </li>
              ))}
            </ul>
          </section>
        )}

        {deployments.length > 0 && (
          <section>
            <h5>Deployments</h5>
            <ul className="source-list">
              {deployments.map((d) => (
                <li key={d.deployment_id}>
                  <div className="source-head">
                    <code>{d.deployment_id}</code>
                    <span className="source-title">{d.change}</span>
                  </div>
                  <div className="source-meta">{join([d.service, d.time?.replace("T", " ")])}</div>
                </li>
              ))}
            </ul>
          </section>
        )}

        {timeline.length > 0 && (
          <section>
            <h5>Timeline</h5>
            <Timeline events={timeline} />
          </section>
        )}

        {logs.length > 0 && (
          <section>
            <h5>Log lines</h5>
            <pre className="log-block">
              {logs.map((e) => join([e.timestamp, e.service, e.level, e.message]).replaceAll(" · ", "  ")).join("\n")}
            </pre>
          </section>
        )}

        {runbook && (
          <section>
            <h5>Runbook guidance <span className="muted">({runbook.title || runbook.name})</span></h5>
            <pre className="runbook-block">{runbook.content}</pre>
            <p className="muted small">Runbooks are guidance, not evidence that anything happened.</p>
          </section>
        )}

        {cited.length > 0 && (
          <section>
            <h5>{investigation.answer_source === "analytics" ? "Counts and the records they cover" : "Facts cited"}</h5>
            <ul className="cited">{cited.map((c, i) => <li key={i}>{c}</li>)}</ul>
          </section>
        )}
      </div>
    </details>
  );
}
