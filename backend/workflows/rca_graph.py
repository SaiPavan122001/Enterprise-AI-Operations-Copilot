"""LangGraph RCA investigation workflow.

Flow:
    START -> question_analysis -> incident_retrieval -> incident_matching
          -> deployment_correlation -> log_retrieval -> runbook_retrieval
          -> evidence_aggregation -> evidence_validation -> rca_generation -> END

incident_matching separates retrieval relevance from evidence: only incidents
judged to describe the asked problem are evidence; deployments (verified
links only), corroborating logs and the runbook are joined to those alone.

All retrieval results are structured evidence models (models/evidence.py).
The evidence validation stage is authoritative for confidence: Gemini cannot
report a confidence level higher than the assessed evidence strength.

Nodes are defensive: a failure in one node is recorded and the workflow
continues so partial evidence can still produce an honest report.
"""

import logging
import re
import time
from typing import NotRequired, TypedDict

from langgraph.graph import END, StateGraph

from agents import analytics
from agents.deployment_agent import investigate_deployments
from agents.gemini_rca_agent import generate_gemini_rca
from agents.deployment_agent import deployment_link_status
from agents.incident_agent import incident_agent
from agents.incident_matcher import (
    MatchResult,
    apply_deterministic_checks,
    match_incidents,
    named_incident_ids,
)
from agents.log_agent import corroborating_logs
from agents.runbook_agent import retrieve_runbook
from models.evidence import (
    EvidenceBundle,
    EvidenceStrength,
    EvidenceValidation,
    RetrievalMetadata,
    RunbookEvidence,
    TimelineEvent,
)
from observability.tracing import InvestigationTracer
from security import access, guardrails, pii
from security.principals import Principal
from utils import cancellation, log_context
from utils.data_integrity import load_dependencies

logger = logging.getLogger(__name__)

STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "why", "what", "which",
    "how", "who", "when", "of", "in", "on", "at", "to", "for", "with",
    "and", "or", "did", "do", "does", "caused", "cause", "latest", "recent",
    "recently", "analyze", "investigate", "about", "that", "this", "it",
}


class RCAState(TypedDict, total=False):
    question: str
    keywords: NotRequired[list[str]]
    incidents: NotRequired[list]  # list[IncidentEvidence] - matched (evidence) after incident_matching
    related_incidents: NotRequired[list]  # retrieved, but not the asked problem
    match: NotRequired[MatchResult]
    deployments: NotRequired[list]  # list[DeploymentEvidence]
    logs: NotRequired[list]  # list[LogEvidence]
    runbook: NotRequired[RunbookEvidence | None]
    bundle: NotRequired[EvidenceBundle]
    validation: NotRequired[EvidenceValidation]
    timeline: NotRequired[list]  # list[TimelineEvent]
    investigation: NotRequired[dict]  # InvestigationResult.model_dump()
    errors: NotRequired[list[str]]
    _incident_scores: NotRequired[list[float]]
    _tracer: NotRequired[InvestigationTracer | None]  # not serialized
    _cancel: NotRequired[cancellation.CancellationToken | None]  # not serialized
    # Authenticated principal (security.principals.Principal), set by the API or an
    # explicit system identity. ABSENT = no record access (deny by default).
    _principal: NotRequired[Principal | None]
    blocked: NotRequired[dict]          # input-rail verdict when the request was declined
    analytics: NotRequired[bool]        # aggregate question: answered by counting records
    guardrail_events: NotRequired[list[str]]


def question_analysis_node(state: RCAState) -> RCAState:
    """Protect and screen the question, then extract keywords.

    1. PII / secrets in the question are redacted BEFORE any LLM call, log line,
       trace or cache entry (security/pii.py).
    2. NeMo input rails screen it (security/guardrails): a blocked request is
       answered by policy without retrieval or generation."""
    logger.info("[LangGraph] Question analysis")
    state["question"] = pii.redact_text(state["question"])
    verdict = guardrails.check_input(state["question"])
    events = state.setdefault("guardrail_events", [])
    events.append(f"input rail ({verdict.engine}, {verdict.latency_ms:.0f} ms): "
                  + (f"blocked - {verdict.reason}" if verdict.blocked else "passed"))
    if verdict.blocked:
        state["blocked"] = {"category": verdict.category, "reason": verdict.reason, "engine": verdict.engine}
        logger.warning("Input rail declined the request (%s)", verdict.category)
    elif analytics.is_aggregate_question(state["question"]):
        # "Where do most incidents happen?" describes no single problem: it is answered
        # by counting authorized records (agents/analytics.py), not by retrieval.
        state["analytics"] = True
    words = re.findall(r"[a-zA-Z0-9_-]+", state["question"].lower())
    state["keywords"] = [w for w in words if w not in STOPWORDS]
    return state


# Every free-text record field that reaches a prompt (the retrieval rail's scope).
INCIDENT_TEXT_FIELDS = ("title", "root_cause", "severity", "status")


def _neutralize_records(state: RCAState, items: list, fields: tuple[str, ...]) -> list:
    """Retrieval rail: record text is untrusted data - instruction-like sentences
    are removed from the given fields before any prompt sees them."""
    texts = [str(getattr(it, f) or "") for it in items for f in fields]
    if not texts:
        return items
    cleaned, changed, engine = guardrails.neutralize_with_engine(texts)
    if engine == "direct":
        state.setdefault("guardrail_events", []).append("retrieval rail ran the checks directly (NeMo unavailable)")
    if changed:
        state.setdefault("guardrail_events", []).append(
            f"retrieval rail: neutralised instruction-like text in {changed} record field(s)")
    out, n = [], 0
    for it in items:
        update = {}
        for f in fields:
            if getattr(it, f):
                update[f] = cleaned[n]
            n += 1
        out.append(it.model_copy(update=update) if update else it)
    return out


def incident_node(state: RCAState) -> RCAState:
    logger.info("[LangGraph] Incident retrieval")
    tracer = state.get("_tracer")
    if tracer:
        tracer.start_stage("incident_retrieval")
    principal = state.get("_principal")
    try:
        if state.get("blocked") or state.get("analytics") or principal is None:
            # declined by the input rail, answered by counting, or no authenticated principal
            result: dict = {"incidents": [], "scores": []}
        else:
            result = incident_agent(state["question"], services=principal.services)
        state["incidents"] = _neutralize_records(
            state, access.filter_by_service(principal, result["incidents"]), INCIDENT_TEXT_FIELDS)
        state["_incident_scores"] = result["scores"]
    except Exception:
        state["incidents"] = []
        state["_incident_scores"] = []
        state.setdefault("errors", []).append("incident_retrieval")
        logger.exception("Incident retrieval node failed")
    finally:
        if tracer:
            tracer.end_stage("incident_retrieval", {"count": len(state["incidents"])})
    return state


def _incidents_raw() -> list[dict]:
    import json

    from config import DATA_DIR

    return json.loads((DATA_DIR / "incidents.json").read_text(encoding="utf-8"))


def _known_services() -> set[str]:
    from utils.data_store import get_deployments

    return {i["service"] for i in _incidents_raw()} | {d["service"] for d in get_deployments() if d.get("service")}


def _incident_record(incident_id: str):
    from models.evidence import IncidentEvidence

    for i in _incidents_raw():
        if i["id"] == incident_id:
            return IncidentEvidence(incident_id=i["id"], service=i.get("service"),
                                    severity=i.get("severity"), status=i.get("status"),
                                    title=i.get("title"), root_cause=i.get("root_cause"),
                                    deployment_id=i.get("deployment_id"), relevance_score=None)
    return None


def incident_matching_node(state: RCAState) -> RCAState:
    """Keep only incidents that describe the problem asked about."""
    logger.info("[LangGraph] Incident matching")
    tracer = state.get("_tracer")
    if tracer:
        tracer.start_stage("incident_matching")
    candidates = list(state.get("incidents", []))
    # An incident named by ID is evidence even if retrieval ranked it out.
    known = {c.incident_id for c in candidates}
    principal = state.get("_principal")
    for iid in sorted(named_incident_ids(state["question"]) - known):
        record = _incident_record(iid)
        # A named record the principal may not read is treated exactly like a
        # non-existent one (its existence is not disclosed).
        skip = state.get("blocked") or state.get("analytics")
        if record is not None and access.can_read(principal, record.service) and not skip:
            candidates.extend(_neutralize_records(state, [record], INCIDENT_TEXT_FIELDS))
    result = match_incidents(state["question"], candidates)
    result = apply_deterministic_checks(state["question"], result, candidates,
                                        _known_services(), load_dependencies())
    state["match"] = result
    state["incidents"] = candidates
    if result.available:
        matched = set(result.matched_ids)
        state["related_incidents"] = [i for i in candidates if i.incident_id not in matched]
        state["incidents"] = [i for i in candidates if i.incident_id in matched]
    else:
        # Check unavailable: keep relevance-filtered incidents, unverified
        # (evidence validation caps strength at LOW and says so).
        state["related_incidents"] = []
        state.setdefault("errors", []).append("incident_matching")
    if tracer:
        tracer.end_stage("incident_matching", {"candidates": len(candidates),
                                               "matched": len(state["incidents"]),
                                               "available": result.available})
    return state


def deployment_node(state: RCAState) -> RCAState:
    logger.info("[LangGraph] Deployment correlation")
    tracer = state.get("_tracer")
    if tracer:
        tracer.start_stage("deployment_correlation")
    try:
        state["deployments"] = _neutralize_records(
            state, access.filter_by_service(state.get("_principal"), investigate_deployments(state["incidents"])),
            ("change",))
    except Exception:
        state["deployments"] = []
        state.setdefault("errors", []).append("deployment_correlation")
        logger.exception("Deployment correlation node failed")
    finally:
        if tracer:
            tracer.end_stage("deployment_correlation", {"count": len(state["deployments"])})
    return state

def log_node(state: RCAState) -> RCAState:
    logger.info("[LangGraph] Log retrieval")
    tracer = state.get("_tracer")
    if tracer:
        tracer.start_stage("log_retrieval")
    try:
        # Only lines that corroborate a matched incident on its own service.
        state["logs"] = _neutralize_records(
            state, access.filter_by_service(state.get("_principal"),
                                            corroborating_logs(state["incidents"], state.get("deployments"))),
            ("message", "level"))
    except Exception:
        state["logs"] = []
        state.setdefault("errors", []).append("log_retrieval")
        logger.exception("Log retrieval node failed")
    finally:
        if tracer:
            tracer.end_stage("log_retrieval", {"count": len(state["logs"])})
    return state


def runbook_node(state: RCAState) -> RCAState:
    logger.info("[LangGraph] Runbook retrieval")
    tracer = state.get("_tracer")
    if tracer:
        tracer.start_stage("runbook_retrieval")
    try:
        # Only the best-matching incident informs the runbook choice; with no
        # matched incident there is no established problem to remediate.
        runbook = (retrieve_runbook(state["question"], state["incidents"][:1])
                   if state["incidents"] else None)
        if runbook is not None and not access.can_read_runbook(state.get("_principal"), runbook.name):
            runbook = None          # runbook not mapped to the principal's services: denied
        state["runbook"] = _neutralize_records(state, [runbook], ("content", "title"))[0] if runbook else None
    except Exception:
        state["runbook"] = None
        state.setdefault("errors", []).append("runbook_retrieval")
        logger.exception("Runbook retrieval node failed")
    finally:
        if tracer:
            tracer.end_stage("runbook_retrieval", {})
    return state

def evidence_aggregation_node(state: RCAState) -> RCAState:
    """Aggregate all structured retrieval results into one EvidenceBundle."""
    logger.info("[LangGraph] Evidence aggregation")
    scores = state.get("_incident_scores") or []
    match = state.get("match")
    state["bundle"] = EvidenceBundle(
        question=state["question"],
        incident_evidence=state.get("incidents", []),
        deployment_evidence=state.get("deployments", []),
        log_evidence=state.get("logs", []),
        runbook_evidence=state.get("runbook"),
        related_incident_evidence=state.get("related_incidents", []),
        match_assessments=match.assessments if match else [],
        match_available=match.available if match else True,
        question_scope=match.question_scope if match else "incident_investigation",
        link_notes=[f"{i.incident_id}: {detail}"
                    for i in state.get("incidents", [])
                    for status, detail in [_link_status(state.get("_principal"), i)]
                    if status in ("quarantined", "missing")],
        retrieval_metadata=RetrievalMetadata(
            incident_count=len(state.get("incidents", [])),
            deployment_count=len(state.get("deployments", [])),
            log_count=len(state.get("logs", [])),
            runbook_count=1 if state.get("runbook") else 0,
            min_relevance_score=min(scores) if scores else None,
            retrieval_errors=state.get("errors", []),
        ),
    )
    return state


def _build_timeline(bundle: EvidenceBundle) -> list[TimelineEvent]:
    """Derive a timeline ONLY from real timestamps present in the data.

    Sources: deployment times (deployments.json) and parsed log entry
    timestamps (logs.txt). If no timestamps exist, the timeline is empty -
    nothing is ever invented.
    """
    events: list[TimelineEvent] = []
    for deployment in bundle.deployment_evidence:
        if deployment.time:
            events.append(
                TimelineEvent(
                    timestamp=deployment.time,
                    event=(
                        f"Deployment {deployment.deployment_id} executed on "
                        f"{deployment.service}: {deployment.change}"
                    ),
                    source="deployments.json",
                )
            )
    for entry in bundle.log_evidence:
        if entry.timestamp and entry.level in ("ERROR", "CRITICAL", "WARN"):
            events.append(
                TimelineEvent(
                    timestamp=entry.timestamp,
                    event=f"{entry.level} on {entry.service}: {entry.message}",
                    source="logs.txt",
                )
            )
    events.sort(key=lambda e: e.timestamp)
    return events[:15]

UNCOVERED_PREFIX = "No retrieved incident record describes"


def _link_status(principal: Principal | None, incident) -> tuple[str, str | None]:
    """deployment_link_status for prompts and answers: without the deployment's own
    change text (untrusted, and not evidence for a quarantined link), and scoped to
    the services the principal may read."""
    status, detail = deployment_link_status(incident, include_change=False)
    return status, access.scoped_detail(principal, detail)


def _incident_strength(incident, bundle: EvidenceBundle, strong_cut: float,
                       principal: Principal | None = None) -> tuple[EvidenceStrength, list, list]:
    """Strength of the evidence for ONE matched incident.
    Returns (strength, missing_evidence, contradictions)."""
    missing, contradictions = [], []
    dep = next((d for d in bundle.deployment_evidence if d.incident_id == incident.incident_id), None)
    logs = [e for e in bundle.log_evidence if e.incident_id == incident.incident_id]
    status, detail = _link_status(principal, incident)
    if status in ("quarantined", "missing"):
        contradictions.append(f"{incident.incident_id}: deployment link {detail}")
    elif dep is None:
        missing.append(f"{incident.incident_id}: no deployment is linked to this incident")
    if not logs:
        missing.append(f"{incident.incident_id}: no log lines on {incident.service} corroborate this incident")
    strong = incident.relevance_score is not None and incident.relevance_score >= strong_cut
    strength: EvidenceStrength
    if contradictions:
        strength = "LOW"
    elif dep is not None and logs and strong:
        strength = "HIGH"
    elif dep is not None or logs:
        strength = "MEDIUM"
    else:
        strength = "LOW"
    return strength, missing, contradictions


def evidence_validation_node(state: RCAState) -> RCAState:
    """Validate the aggregated evidence and assess overall strength.

    Retrieval relevance is not causal evidence. For each MATCHED incident:
    - HIGH:   its own verified deployment + corroborating logs on its service
              (time-aligned) + a strong retrieval match, and no contradictions
    - MEDIUM: a verified deployment OR corroborating logs, no contradictions
    - LOW:    only the incident record itself, or contradictory evidence
              (e.g. its deployment link points at another service)
    - INSUFFICIENT: no retrieved incident describes the asked problem
    The overall strength is the weakest across matched incidents (a
    multi-incident answer is only as strong as its weakest part). If the
    match check could not run, strength is capped at LOW. Missing and
    contradictory evidence is recorded and shown in the report.
    """
    from config import settings

    logger.info("[LangGraph] Evidence validation")
    bundle = state["bundle"]
    meta = bundle.retrieval_metadata
    validation = EvidenceValidation(
        incident_found=meta.incident_count > 0,
        deployment_found=meta.deployment_count > 0,
        logs_found=meta.log_count > 0,
        runbook_found=meta.runbook_count > 0,
    )
    notes: list[str] = []
    if not bundle.incident_evidence:
        validation.evidence_strength = "INSUFFICIENT"
        notes.append("No retrieved incident describes the problem asked about.")
    else:
        ranks = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}
        strengths: list[EvidenceStrength] = []
        for incident in bundle.incident_evidence:
            s, missing, contradictions = _incident_strength(
                incident, bundle, settings.STRONG_RELEVANCE_SCORE, state.get("_principal"))
            strengths.append(s)
            validation.missing_evidence += missing
            validation.contradictions += contradictions
        overall = min(strengths, key=lambda s: ranks[s])
        causes = {i.incident_id: i.root_cause for i in bundle.incident_evidence}
        if len(set(causes.values())) > 1:
            notes.append("Matched incidents record different root causes ("
                         + "; ".join(f"{k}: {v}" for k, v in causes.items())
                         + "); each is reported separately, none is merged or chosen silently.")
        if not bundle.match_available:
            overall = "LOW"
            notes.append("The evidence match check was unavailable; incidents are relevance matches only.")
        validation.evidence_strength = overall

    # Parts of a multi-incident question that no retrieved record addresses are
    # stated, never silently dropped (rca_structured adds them to the summary).
    match = state.get("match")
    for req in (match.uncovered if match is not None else []):
        validation.missing_evidence.append(f"{UNCOVERED_PREFIX} \"{req['problem']}\", which the question asks about.")

    for err in meta.retrieval_errors:
        if err != "rca_generation":
            notes.append(f"Retrieval stage reported an issue: {err}.")

    # Notes about records outside the principal's scope (e.g. a quarantined link to
    # another service's deployment) are generalised, not disclosed.
    principal = state.get("_principal")
    validation.contradictions = [access.scoped_detail(principal, c) or c for c in validation.contradictions]
    validation.missing_evidence = [access.scoped_detail(principal, m) or m for m in validation.missing_evidence]
    validation.notes = notes
    state["validation"] = validation
    state["timeline"] = _build_timeline(bundle)
    logger.info(
        "Evidence validation: strength=%s matched=%d deployments=%d logs=%d contradictions=%d",
        validation.evidence_strength, len(bundle.incident_evidence),
        len(bundle.deployment_evidence), len(bundle.log_evidence), len(validation.contradictions),
    )
    return state

def rca_node(state: RCAState) -> RCAState:
    logger.info("[LangGraph] RCA generation")
    tracer = state.get("_tracer")
    span = tracer.start_stage("rca_generation") if tracer else None
    try:
        if state.get("blocked"):
            from agents.gemini_rca_agent import guardrail_refusal

            result = guardrail_refusal(state["bundle"], state["validation"], state["blocked"])
        elif state.get("analytics"):
            result = analytics.analytics_result(state["bundle"], state["validation"], state.get("_principal"))
        else:
            result = generate_gemini_rca(
                bundle=state["bundle"],
                validation=state["validation"],
                timeline=state.get("timeline", []),
                trace_span=span,
            )
        result.guardrail_events = list(state.get("guardrail_events", [])) + result.guardrail_events
        state["investigation"] = result.model_dump()
    except Exception:
        logger.exception("RCA generation node failed unexpectedly")
        from agents.gemini_rca_agent import _fallback_result

        fallback = _fallback_result(
            state["bundle"], state["validation"], state.get("timeline", [])
        )
        state["investigation"] = fallback.model_dump()
    finally:
        if tracer:
            tracer.end_stage("rca_generation", {})

    investigation = state["investigation"]
    if tracer:
        tracer.end(
            metadata={
                "status": investigation.get("status"),
                "confidence": investigation.get("confidence"),
                "evidence_strength": investigation.get("evidence_strength"),
                "incident_count": len(investigation["evidence"]["incident_evidence"]),
                "deployment_count": len(investigation["evidence"]["deployment_evidence"]),
                "log_count": len(investigation["evidence"]["log_evidence"]),
            }
        )
    return state


def _cancellable(stage: str, node):
    """Run one workflow stage: check the request's cancellation token first and
    expose it to the code the stage calls (the LLM layer checks it before each
    attempt and during backoff); log the stage's duration and outcome with the
    stage in the log context."""
    def run(state: RCAState) -> RCAState:
        token = state.get("_cancel")
        if token is not None:
            token.raise_if_cancelled(stage)
        bound = cancellation.bind(token)
        ctx = log_context.set_context(stage=stage)
        start, outcome = time.perf_counter(), "error"
        try:
            result = node(state)
            outcome = "ok"
            return result
        except cancellation.InvestigationCancelled:
            outcome = "cancelled"
            raise
        finally:
            logger.info("Stage %s %s", stage, outcome,
                        extra={"outcome": outcome, "duration_ms": round((time.perf_counter() - start) * 1000)})
            log_context.reset_context(ctx)
            cancellation.unbind(bound)

    run.__name__ = node.__name__
    return run


graph = StateGraph(RCAState)
for _stage, _node in (("question_analysis", question_analysis_node), ("incident_retrieval", incident_node),
                      ("incident_matching", incident_matching_node),
                      ("deployment_correlation", deployment_node), ("log_retrieval", log_node),
                      ("runbook_retrieval", runbook_node), ("evidence_aggregation", evidence_aggregation_node),
                      ("evidence_validation", evidence_validation_node), ("rca_generation", rca_node)):
    graph.add_node(_stage, _cancellable(_stage, _node))

graph.set_entry_point("question_analysis")
graph.add_edge("question_analysis", "incident_retrieval")
graph.add_edge("incident_retrieval", "incident_matching")
graph.add_edge("incident_matching", "deployment_correlation")
graph.add_edge("deployment_correlation", "log_retrieval")
graph.add_edge("log_retrieval", "runbook_retrieval")
graph.add_edge("runbook_retrieval", "evidence_aggregation")
graph.add_edge("evidence_aggregation", "evidence_validation")
graph.add_edge("evidence_validation", "rca_generation")
graph.add_edge("rca_generation", END)

app = graph.compile()

# Node -> SSE stage id (real workflow progress for the streaming endpoint)
NODE_STAGE_IDS = {
    "question_analysis": "question_analysis",
    "incident_retrieval": "incident_retrieval",
    "incident_matching": "incident_matching",
    "deployment_correlation": "deployment_correlation",
    "log_retrieval": "log_retrieval",
    "runbook_retrieval": "runbook_retrieval",
    "evidence_aggregation": "evidence_aggregation",
    "evidence_validation": "evidence_validation",
    "rca_generation": "rca_generation",
}


def run_investigation(question: str, tracer: InvestigationTracer | None = None, principal=None) -> dict:
    """Invoke the workflow with optional tracing; returns the final state.
    Without a principal no record is readable (deny by default)."""
    return app.invoke({"question": question, "_tracer": tracer, "_principal": principal})


if __name__ == "__main__":
    import json

    result = run_investigation("Why is payroll failing?", principal=access.system_principal("cli"))
    print("\n========== STRUCTURED RCA ==========\n")
    print(json.dumps(result["investigation"], indent=2, default=str))

