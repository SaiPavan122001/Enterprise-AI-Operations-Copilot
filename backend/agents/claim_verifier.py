"""Runtime claim-support verification.

A valid citation proves only that a claim points at a real record (provenance),
not that the record SUPPORTS the claim. This module checks support:

1. Deterministic checks (always on unless CLAIM_VERIFIER=off):
   * a service named in a claim must be the service of a record it cites, or a
     service the application's own evidence notes mention (e.g. the service of
     a quarantined deployment);
   * a severity named in a claim must be the severity of the incidents it cites;
   * a number in a STATED claim (fact / impact) must appear in the evidence - an
     invented count or duration ("4,200 users", "3 hours") is not stated.
2. A semantic verifier (CLAIM_VERIFIER=nli): a local NLI cross-encoder reads the
   cited records PLUS the application's evidence notes (missing logs, unverified
   links) and flags claims it finds CONTRADICTED with high confidence.
   It is a fallible model, so it is used only where it is reliable:
   * statements of absence/negation ("no log lines corroborate ...") are not sent
     to it - on real answers it judged true absence statements as contradictions;
   * "neutral" (not entailed) is not acted on - on real answers it marked correct
     multi-fact restatements of a record as neutral;
   * only p(contradiction) >= CONTRADICTION_MIN removes a claim.
   Error rates on labelled examples: evals/claim_verifier_eval.py.

The verifier only removes or downgrades claims (never rewrites them), and every
change is reported in the answer's grounding issues. If the model cannot be
loaded the deterministic checks still run and the answer says so.
"""

import logging
import re
import threading
from typing import Any

from agents.rca_structured import log_ids
from config import settings

logger = logging.getLogger(__name__)

SUPPORTED, NEUTRAL, CONTRADICTED, SKIPPED = "supported", "neutral", "contradicted", "skipped"
CONTRADICTION_MIN = 0.9
SERVICE_RE = re.compile(r"\b[a-z]+-service\b")
SEVERITY_WORD_RE = re.compile(r"\b(critical|high|medium|low)[- ]?(?:severity|priority)\b|\bseverity (?:of |level )?"
                              r"(critical|high|medium|low)\b|\b(critical)\b", re.IGNORECASE)
# Statements of absence / negation: deterministic checks only (NLI unreliable on them).
ABSENCE_RE = re.compile(r"\b(?:no|not|none|never|neither|nor|without|cannot|lacks?|lacking|absent|absence|"
                        r"unverified|unknown|unclear|undetermined|missing)\b|n't\b", re.IGNORECASE)
NUMBER_RE = re.compile(r"(?<![\w-])\d[\d,.]*(?:%|\b)")

_model = None
_label_index: tuple[int, int, int] = (0, 1, 2)   # (contradiction, entailment, neutral) of the loaded model
_model_error: str | None = None
_lock = threading.Lock()


def record_texts(bundle) -> dict[str, str]:
    """Plain-text form of every record a claim may cite (the NLI premise)."""
    out = {i.incident_id: (f"Incident {i.incident_id} on {i.service}: {i.title}. Severity {i.severity}. "
                           f"Status {i.status}. Recorded root cause: {i.root_cause}.")
           for i in bundle.incident_evidence}
    out.update({d.deployment_id: (f"Deployment {d.deployment_id} on {d.service} at {d.time}: {d.change}. "
                                  f"It is linked to incident {d.incident_id}.")
                for d in bundle.deployment_evidence})
    out.update({lid: f"Log line {lid} at {e.timestamp} on {e.service}, level {e.level}: {e.message}"
                for lid, e in log_ids(bundle).items()})
    if bundle.runbook_evidence:
        out["RUNBOOK"] = f"Runbook {bundle.runbook_evidence.title}: {bundle.runbook_evidence.content[:1500]}"
    return out


def evidence_context(bundle, notes: list[str]) -> str:
    """What the application itself established about missing evidence - part of
    the evidence the answer was written from."""
    linked = {d.incident_id for d in bundle.deployment_evidence}
    facts = list(notes)
    if not bundle.log_evidence:
        facts.append("No log line corroborates any matched incident.")
    facts += [f"No verified deployment link exists for {i.incident_id}." for i in bundle.incident_evidence
              if i.incident_id not in linked]
    return " ".join(facts)


def deterministic_problems(statement: str, refs: list[str], bundle, notes_text: str = "",
                           stated: bool = False, evidence_text: str = "") -> list[str]:
    """Record-membership checks that need no model."""
    problems = []
    cited_incidents = [i for i in bundle.incident_evidence if i.incident_id in refs]
    cited_services = {i.service for i in cited_incidents}
    cited_services |= {d.service for d in bundle.deployment_evidence if d.deployment_id in refs}
    cited_services |= {e.service for lid, e in log_ids(bundle).items() if lid in refs}
    allowed = cited_services | set(SERVICE_RE.findall(notes_text.lower()))
    named = set(SERVICE_RE.findall(statement.lower()))
    # A statement of missing evidence may name the service of a part of the question
    # that no record covers ("no record describes the reporting-service impact").
    if cited_services and named - allowed and not states_absence(statement):
        problems.append(f"names {sorted(named - allowed)} but cites records on {sorted(cited_services)}")
    severities = {next(g for g in m.groups() if g).lower() for m in SEVERITY_WORD_RE.finditer(statement)}
    cited_sev = {str(i.severity).lower() for i in cited_incidents}
    # Only when the claim cites incidents only: a severity cannot be checked against a log/runbook.
    if severities and cited_incidents and len(cited_incidents) == len(refs) and severities - cited_sev:
        problems.append(f"states severity {sorted(severities)} but the cited incidents are {sorted(cited_sev)}")
    if stated:
        # IDs (INC-001, DEP-101, LOG-2) and dates are checked elsewhere; strip them first.
        bare = re.sub(r"\b(?:INC|DEP|LOG)-\d+\b|\b20\d{2}-\d{2}-\d{2}(?:[T ][\d:]+)?", " ", statement)
        # Compare digit groups, so "10:00" matches a "2026-05-14T10:00:00" timestamp
        # and "4,200" must appear as 4200.
        evidence_digits = set(re.findall(r"\d+", evidence_text.replace(",", "")))
        invented = [n for n in NUMBER_RE.findall(bare)
                    if not set(re.findall(r"\d+", n.replace(",", ""))) <= evidence_digits]
        if invented:
            problems.append(f"states figures not in the evidence ({', '.join(invented)})")
    cited_text = " ".join(t for r, t in record_texts(bundle).items() if r in refs)
    problems += record_contradictions(statement, cited_incidents, bundle, cited_text)
    return problems


# --------------------------------------------------------------------------- record contradictions
# Each rule compares what a claim says about a CITED incident with that incident's
# record. They are phrased as general sentence patterns (not tied to any test
# question) and each returns a reason; a match removes the claim.

STATUS_OPEN_RE = re.compile(
    r"\b(?:unresolved|still (?:open|ongoing|active|occurring|happening|unresolved|in progress)"
    r"|remains? (?:open|unresolved|active|ongoing)|(?:has|have) not (?:yet )?been (?:resolved|fixed|closed)"
    r"|(?:is|was|are|were) not (?:yet )?(?:resolved|fixed|closed)|yet to be (?:resolved|fixed))\b", re.IGNORECASE)
CLOSED_STATUSES = ("resolved", "closed")

# "the (root) cause ... was not X", "X was not the cause", "not caused by X", "did not result from X"
NEG_CAUSE_RES = [
    re.compile(r"\bcause\w*\b[^.;]{0,40}?\b(?:was|is|were|are)(?: not|n't)\b(?P<span>[^.;]*)", re.IGNORECASE),
    re.compile(r"(?P<span>[^.;]*?)\b(?:was|is|were|are)(?: not|n't)\b[^.;]{0,25}?\b(?:root )?cause\b", re.IGNORECASE),
    re.compile(r"\b(?:not|n't|never)\s+(?:been\s+)?(?:caused by|due to|the result of|attributed to|because of|"
               r"triggered by|brought on by)(?P<span>[^.;]*)", re.IGNORECASE),
    re.compile(r"\b(?:did|does|do)(?: not|n't)\s+(?:stem|result|arise|originate)\s+from(?P<span>[^.;]*)",
               re.IGNORECASE),
]
# Claims that a record field is absent.
NO_ROOT_CAUSE_RE = re.compile(
    r"\bno (?:recorded |documented |known |identified )?root cause\b"
    r"|\broot cause(?: of [\w-]+)? (?:was|is|has|had)(?: not|n't| never) (?:been )?(?:recorded|documented|"
    r"identified|determined|"
    r"established|captured|logged|provided|given|specified)"
    r"|\broot cause(?: of [\w-]+)? (?:is|was|remains) "
    r"(?:unknown|undetermined|unidentified|not known|missing)\s*(?:[.;,)]|$)"
    r"|\bwithout (?:a |any )?(?:recorded |documented )?root cause\b"
    r"|\b(?:does|did|do)(?: not|n't) (?:record|document|include|list|specify|state) (?:a |any )?root cause\b",
    re.IGNORECASE)
NO_DEPLOYMENT_RE = re.compile(
    r"\bno (?:verified |linked |associated |recorded |related )?deployment\b"
    r"|\b(?:not|never) (?:been )?(?:linked|associated|tied|connected) (?:to|with) (?:any|a) (?:verified )?deployment\b"
    r"|\bwithout (?:a |any )?(?:verified |linked )?deployment\b", re.IGNORECASE)
NO_LOGS_RE = re.compile(r"\bno (?:corroborating )?log(?: line)?s?\b[^.;]{0,30}\bcorroborat", re.IGNORECASE)


def states_absence(statement: str) -> bool:
    """A negation/absence statement - ignoring negations inside recorded titles or
    causes ("Scheduled reports not generated")."""
    from utils.data_store import get_incidents

    text = statement
    for rec in get_incidents():
        for field in ("title", "root_cause"):
            if rec.get(field):
                text = re.sub(re.escape(rec[field]), " ", text, flags=re.IGNORECASE)
    return bool(ABSENCE_RE.search(text))


def _terms(text: str | None) -> set[str]:
    from agents.rca_structured import _finding_terms
    return _finding_terms(text)


def _covers(span: str, field: str | None) -> bool:
    """The span states the field in substance (>= 2 distinctive terms, or all if fewer)."""
    terms = _terms(field)
    return bool(terms) and len(terms & _terms(span)) >= min(2, len(terms))


def record_contradictions(statement: str, cited: list, bundle, cited_text: str = "") -> list[str]:
    if not cited:
        return []
    problems = []
    closed = all(str(i.status or "").lower() in CLOSED_STATUSES for i in cited)
    if closed and STATUS_OPEN_RE.search(statement):
        problems.append("says the incident is unresolved but the record's status is "
                        + ", ".join(sorted({str(i.status) for i in cited})))
    for rx in NEG_CAUSE_RES:
        m = rx.search(statement)
        if m and any(_covers(m.group("span"), i.root_cause) for i in cited):
            problems.append("negates the recorded root cause")
            break
    # A sentence about ANOTHER (unmatched) incident's missing evidence is not an absence
    # claim about the cited one, and an absence statement does not attribute that other
    # record to the cited incident (real answers: "the cause of the stuck leave approval
    # workflow is not determined from the records").
    about_other = bool(_other_record_attributes(statement, cited, cited_text))
    if not about_other:
        if NO_ROOT_CAUSE_RE.search(statement) and all(i.root_cause for i in cited):
            problems.append("says no root cause is recorded, but the record has one")
        linked = {d.incident_id for d in bundle.deployment_evidence}
        if NO_DEPLOYMENT_RE.search(statement) and all(i.incident_id in linked for i in cited):
            problems.append("says no deployment is linked, but a verified link exists")
        corroborated = {e.incident_id for e in bundle.log_evidence}
        if NO_LOGS_RE.search(statement) and all(i.incident_id in corroborated for i in cited):
            problems.append("says no log line corroborates it, but corroborating log lines exist")
    elif not states_absence(statement):
        problems += _other_record_attributes(statement, cited, cited_text)
    return problems


def _other_record_attributes(statement: str, cited: list, cited_text: str = "") -> list[str]:
    """A claim citing incident A that states uncited incident B's recorded root
    cause or title - words that none of the claim's cited records (incident,
    deployment, log) contain - attributes B's record to A."""
    from utils.data_store import get_incidents

    cited_ids = {i.incident_id for i in cited}
    own = _terms(cited_text)
    for i in cited:
        own |= _terms(i.root_cause) | _terms(i.title)
    words = _terms(statement)
    for rec in get_incidents():
        if rec.get("id") in cited_ids:
            continue
        for field in ("root_cause", "title"):
            terms = _terms(rec.get(field))
            # Only distinctive fields (>= 2 terms), fully stated, and not also the cited record's own words.
            if len(terms) >= 2 and terms <= words and not terms <= own:
                return [f"states {rec['id']}'s recorded {field.replace('_', ' ')} ({rec.get(field)!r}) "
                        f"for {', '.join(sorted(cited_ids))}"]
    return []


def _load():
    global _model, _model_error, _label_index
    with _lock:
        if _model is None and _model_error is None:
            try:
                from sentence_transformers import CrossEncoder
                _model = CrossEncoder(settings.CLAIM_VERIFIER_MODEL,
                                      revision=settings.CLAIM_VERIFIER_MODEL_REVISION or None)
                labels = {v.lower(): k for k, v in _model.config.id2label.items()}
                _label_index = (labels["contradiction"], labels["entailment"], labels["neutral"])
            except Exception as exc:   # missing package / offline / bad model name
                _model_error = type(exc).__name__
                logger.warning("Claim verifier model unavailable (%s); deterministic checks only", _model_error)
    return _model


def nli_verdicts(pairs: list[tuple[str, str]]) -> list[str] | None:
    """(premise, claim) -> contradicted (p >= CONTRADICTION_MIN) | supported | neutral; None if no model."""
    if settings.CLAIM_VERIFIER != "nli":
        return None
    if not pairs:
        return []
    model = _load()
    if model is None:
        return None
    ci, ei, ni = _label_index
    out = []
    for probs in model.predict(pairs, apply_softmax=True, batch_size=16, show_progress_bar=False):
        if probs[ci] >= CONTRADICTION_MIN:
            out.append(CONTRADICTED)
        else:
            out.append(SUPPORTED if probs[ei] >= probs[ni] else NEUTRAL)
    return out


def verify_claims(claims: list[dict], bundle, notes: list[str] | None = None) -> list[dict]:
    """Per claim ({"statement", "refs", optional "stated"}): {"deterministic": [problems],
    "semantic": contradicted | supported | neutral | skipped | None (no model)}."""
    if settings.CLAIM_VERIFIER == "off":
        return [{"deterministic": [], "semantic": None} for _ in claims]
    notes = notes or []
    texts = record_texts(bundle)
    context = evidence_context(bundle, notes)
    notes_text = " ".join(notes)
    all_evidence = " ".join(texts.values()) + " " + context
    results: list[dict[str, Any]] = [
        {"deterministic": deterministic_problems(c["statement"], c["refs"], bundle, notes_text,
                                                 c.get("stated", False), all_evidence),
         "semantic": None}
        for c in claims]
    to_check = [n for n, c in enumerate(claims) if not ABSENCE_RE.search(c["statement"])]
    for n in set(range(len(claims))) - set(to_check):
        results[n]["semantic"] = SKIPPED
    pairs = [(" ".join([texts[r] for r in claims[n]["refs"] if r in texts] + [context]), claims[n]["statement"])
             for n in to_check]
    verdicts = nli_verdicts(pairs)
    if verdicts is None:
        for n in to_check:
            results[n]["semantic"] = None
    else:
        for n, v in zip(to_check, verdicts):
            results[n]["semantic"] = v
    return results


def semantic_available() -> bool:
    return settings.CLAIM_VERIFIER == "nli" and _load() is not None
