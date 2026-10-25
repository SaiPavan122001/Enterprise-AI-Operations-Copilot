import { useCallback, useEffect, useState } from "react";
import {
  approveAction, executeAction, invokeTool, listActions, listTools, proposeAction, rejectAction,
} from "../services/api";
import { CloseIcon } from "./Icons";

/**
 * Tools and the human-approval workflow (SIMULATED remediation only).
 * The UI only displays what the backend allows; every rule (permissions,
 * separation of duties, expiry, argument binding, single use) is enforced
 * server-side.
 */
export default function ActionsPanel({ identity, onClose }) {
  const [tools, setTools] = useState([]);
  const [actions, setActions] = useState([]);
  const [error, setError] = useState(null);
  const [lookup, setLookup] = useState({ tool: "incident_lookup", id: "" });
  const [lookupResult, setLookupResult] = useState(null);
  const [proposal, setProposal] = useState({ tool: "simulated_rollback_deployment", target: "", reason: "" });
  const can = (p) => identity.permissions.includes(p);

  const refresh = useCallback(async () => {
    try {
      const [t, a] = await Promise.all([listTools(), listActions()]);
      setTools(t.tools);
      setActions(a.actions);
      setError(null);
    } catch (err) {
      setError(err.message);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    const esc = (e) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", esc);
    return () => document.removeEventListener("keydown", esc);
  }, [onClose]);

  const run = async (fn) => {
    try {
      setError(null);
      await fn();
      await refresh();
    } catch (err) {
      setError(err.message);
    }
  };

  const doLookup = () => run(async () => {
    const key = lookup.tool === "incident_lookup" ? "incident_id" : "deployment_id";
    const res = await invokeTool(lookup.tool, { [key]: lookup.id.trim() });
    setLookupResult(res.result);
  });

  const doPropose = () => run(async () => {
    const args = proposal.tool === "simulated_rollback_deployment"
      ? { deployment_id: proposal.target.trim(), reason: proposal.reason }
      : { service: proposal.target.trim(), mode: "rolling", reason: proposal.reason };
    await proposeAction(proposal.tool, args);
    setProposal({ ...proposal, target: "", reason: "" });
  });

  const readTools = tools.filter((t) => !t.consequential);
  const actionTools = tools.filter((t) => t.consequential);

  return (
    <>
    <div className="scrim visible drawer-scrim" onClick={onClose} aria-hidden="true" />
    <aside className="drawer" role="dialog" aria-label="Tools and approvals">
      <div className="drawer-head">
        <div>
          <h2>Tools &amp; approvals</h2>
          <p className="muted small">Remediation is simulated. Every action needs a second person to approve it.</p>
        </div>
        <button className="icon-btn" onClick={onClose} aria-label="Close tools panel"><CloseIcon /></button>
      </div>
      {error && <p className="form-error" role="alert">{error}</p>}

      {readTools.length > 0 && (
        <section>
          <h3>Look up a record</h3>
          <div className="row">
            <select value={lookup.tool} onChange={(e) => setLookup({ ...lookup, tool: e.target.value })}>
              {readTools.map((t) => <option key={t.name} value={t.name}>{t.name}</option>)}
            </select>
            <input placeholder={lookup.tool === "incident_lookup" ? "INC-001" : "DEP-101"} value={lookup.id}
              onChange={(e) => setLookup({ ...lookup, id: e.target.value })} maxLength={10} />
            <button className="primary-btn" onClick={doLookup}>Look up</button>
          </div>
          {lookupResult && <pre className="tool-result">{JSON.stringify(lookupResult, null, 2)}</pre>}
        </section>
      )}

      {can("actions:propose") && actionTools.length > 0 && (
        <section>
          <h3>Propose a remediation (needs approval by another person)</h3>
          <div className="row">
            <select value={proposal.tool} onChange={(e) => setProposal({ ...proposal, tool: e.target.value })}>
              {actionTools.map((t) => <option key={t.name} value={t.name}>{t.name}</option>)}
            </select>
            <input placeholder={proposal.tool === "simulated_rollback_deployment" ? "DEP-101" : "payroll-service"}
              value={proposal.target} onChange={(e) => setProposal({ ...proposal, target: e.target.value })}
              maxLength={40} />
          </div>
          <textarea placeholder="Reason (10-300 characters)" value={proposal.reason} maxLength={300}
            onChange={(e) => setProposal({ ...proposal, reason: e.target.value })} />
          <button className="primary-btn" onClick={doPropose}>Propose action</button>
        </section>
      )}

      <section>
        <h3>Actions</h3>
        {actions.length === 0 && <p className="muted">No actions you can see.</p>}
        {actions.map((a) => {
          const mine = a.requester === identity.user;
          return (
            <div key={a.id} className={`action-card status-${a.status}`}>
              <div className="action-title"><b>{a.tool}</b> <span className={`chip status-chip ${a.status}`}>{a.status}</span></div>
              <dl>
                <dt>Arguments (validated)</dt><dd><code>{JSON.stringify(a.args)}</code></dd>
                <dt>Argument hash</dt><dd><code>{a.args_hash.slice(0, 16)}…</code></dd>
                <dt>Requested by</dt><dd>{a.requester} ({a.requester_role}) at {a.created_at}</dd>
                <dt>Impact</dt><dd>{a.impact}</dd>
                {a.approved_by && <><dt>Approved by</dt><dd>{a.approved_by} (valid until {a.approval_expires_at})</dd></>}
                {a.rejected_by && <><dt>Rejected by</dt><dd>{a.rejected_by}</dd></>}
                {a.result && <><dt>Result</dt><dd><code>{JSON.stringify(a.result)}</code></dd></>}
              </dl>
              <div className="row">
                {a.status === "pending" && can("actions:approve") && !mine && (
                  <>
                    <button className="primary-btn" onClick={() => run(() => approveAction(a.id, a.args_hash))}>
                      Approve exactly this
                    </button>
                    <button className="secondary-btn" onClick={() => run(() => rejectAction(a.id, a.args_hash))}>
                      Reject
                    </button>
                  </>
                )}
                {a.status === "pending" && mine && <span className="muted">Waiting for another approver.</span>}
                {a.status === "approved" && (mine || can("actions:approve")) && can("actions:execute") && (
                  <button className="primary-btn" onClick={() => run(() => executeAction(a.id, a.args))}>
                    Execute (simulated)
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </section>
    </aside>
    </>
  );
}
