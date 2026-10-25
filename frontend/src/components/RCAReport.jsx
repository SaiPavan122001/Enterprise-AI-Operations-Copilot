import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import EvidencePanel from "./EvidencePanel";
import Feedback from "./Feedback";
import { CheckIcon, ChevronIcon, CopyIcon } from "./Icons";

function Md({ children }) {
  return <ReactMarkdown remarkPlugins={[remarkGfm]}>{children || ""}</ReactMarkdown>;
}

const norm = (t) => (t || "").replace(/\[[^\]]*\]/g, "").replace(/[^a-z0-9]+/gi, " ").trim().toLowerCase();
// The summary often already states the root cause; don't print it twice.
const repeats = (summary, text) => norm(text).length > 0 && norm(summary).includes(norm(text));

const meaningful = (text) => text && !/^(not (recorded|applicable|determined)|none identified|n\/a)/i.test(text.trim());

function Section({ title, items, ordered }) {
  const list = (items || []).filter(meaningful);
  if (list.length === 0) return null;
  const Tag = ordered ? "ol" : "ul";
  return (
    <>
      <h4>{title}</h4>
      <Tag>{list.map((item, i) => <li key={i}><Md>{item}</Md></li>)}</Tag>
    </>
  );
}

function plainText(inv, report) {
  if (!inv) return report || "";
  if (inv.answer_source === "analytics") return inv.report_markdown || inv.summary || "";
  const parts = [inv.summary];
  if (meaningful(inv.root_cause)) parts.push(`Root cause: ${inv.root_cause}`);
  for (const [label, items] of [["Recommended remediation", inv.recommended_remediation],
    ["Preventive actions", inv.preventive_actions]]) {
    if (items?.length) parts.push(`${label}:\n${items.map((x) => `- ${x}`).join("\n")}`);
  }
  return parts.filter(Boolean).join("\n\n");
}

function CopyButton({ text }) {
  const [done, setDone] = useState(false);
  return (
    <button
      className="icon-btn small"
      onClick={() => {
        navigator.clipboard?.writeText(text).then(() => {
          setDone(true);
          setTimeout(() => setDone(false), 1500);
        }).catch(() => {});
      }}
      aria-label="Copy answer"
      title={done ? "Copied" : "Copy"}
    >
      {done ? <CheckIcon size={16} /> : <CopyIcon size={16} />}
    </button>
  );
}

/** One assistant answer, rendered as plain prose with optional detail sections. */
export default function RCAReport({ investigation: inv, report, notice }) {
  if (!inv) {
    return <div className="answer"><Md>{report || "_No answer was returned._"}</Md></div>;
  }

  const source = inv.answer_source;
  const declined = source === "guardrail" || ["blocked", "out_of_scope"].includes(inv.answer_status);
  const analytics = source === "analytics";
  const caveats = [...new Set([...(inv.validation?.notes || []), ...(inv.unknowns || [])])]
    .filter((c) => c && !analytics);

  return (
    <div className="answer">
      {notice && <p className="notice">{notice}</p>}

      {analytics ? (
        <Md>{(inv.report_markdown || inv.summary || "").replace(/^##[^\n]*\n+/, "")}</Md>
      ) : (
        <>
          <Md>{inv.summary || "_No summary was produced._"}</Md>
          {!declined && (
            <>
              {meaningful(inv.root_cause) && !repeats(inv.summary, inv.root_cause) && (
                <>
                  <h4>Root cause</h4>
                  <Md>{inv.root_cause}</Md>
                </>
              )}
              {meaningful(inv.impact) && (
                <>
                  <h4>Impact</h4>
                  <Md>{inv.impact}</Md>
                </>
              )}
              <Section title="Contributing factors" items={inv.contributing_factors} />
              <Section title="Recommended remediation" items={inv.recommended_remediation} ordered />
              <Section title="Preventive actions" items={inv.preventive_actions} ordered />
              {caveats.length > 0 && (
                <details className="caveats">
                  <summary>
                    <ChevronIcon size={14} className="sources-chevron" />
                    What the records don&apos;t show ({caveats.length})
                  </summary>
                  <ul>{caveats.map((c, i) => <li key={i}>{c}</li>)}</ul>
                </details>
              )}
            </>
          )}
        </>
      )}

      {!declined && <EvidencePanel investigation={inv} />}

      <div className="answer-actions">
        <CopyButton text={plainText(inv, report)} />
        <Feedback />
        {!declined && inv.confidence && (
          <span className={`confidence c-${inv.confidence.toLowerCase()}`}
            title="Confidence is capped by the strength of the evidence the records provide">
            {analytics ? "Exact counts from records" : `Confidence: ${inv.confidence.toLowerCase()}`}
          </span>
        )}
      </div>
    </div>
  );
}
