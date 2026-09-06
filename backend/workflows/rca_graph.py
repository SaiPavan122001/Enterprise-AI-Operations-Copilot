"""LangGraph RCA investigation workflow.

Flow:
    START -> question_analysis -> incident_retrieval -> deployment_correlation
          -> log_retrieval -> runbook_retrieval -> evidence_aggregation
          -> evidence_validation -> rca_generation -> END

All retrieval results are structured evidence models (models/evidence.py).
The evidence validation stage is authoritative for confidence: Gemini cannot
report a confidence level higher than the assessed evidence strength.

Nodes are defensive: a failure in one node is recorded and the workflow
continues so partial evidence can still produce an honest report.
"""

import logging
import re
from typing import NotRequired, TypedDict

from langgraph.graph import END, StateGraph

from agents.deployment_agent import investigate_deployments
from agents.gemini_rca_agent import generate_gemini_rca
from agents.incident_agent import incident_agent
from agents.log_agent import investigate_logs
from agents.runbook_agent import retrieve_runbook
from models.evidence import (
    EvidenceBundle,
    EvidenceValidation,
    RetrievalMetadata,
    TimelineEvent,
)
from observability.tracing import InvestigationTracer

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
    incidents: NotRequired[list]  # list[IncidentEvidence]
    deployments: NotRequired[list]  # list[DeploymentEvidence]
    logs: NotRequired[list]  # list[LogEvidence]
    runbook: NotRequired[object]  # RunbookEvidence | None
    bundle: NotRequired[EvidenceBundle]
    validation: NotRequired[EvidenceValidation]
    timeline: NotRequired[list]  # list[TimelineEvent]
    investigation: NotRequired[dict]  # InvestigationResult.model_dump()
    errors: NotRequired[list[str]]
    _incident_scores: NotRequired[list[float]]
    _tracer: NotRequired[object]  # InvestigationTracer (not serialized)


def question_analysis_node(state: RCAState) -> RCAState:
    """Extract simple investigation keywords from the user question."""
    logger.info("[LangGraph] Question analysis")
    words = re.findall(r"[a-zA-Z0-9_-]+", state["question"].lower())
    state["keywords"] = [w for w in words if w not in STOPWORDS]
    return state


def incident_node(state: RCAState) -> RCAState:
    logger.info("[LangGraph] Incident retrieval")
    tracer = state.get("_tracer")
    span = tracer.start_stage("incident_retrieval") if tracer else None
    try:
        result = incident_agent(state["question"])
        state["incidents"] = result["incidents"]
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


def deployment_node(state: RCAState) -> RCAState:
    logger.info("[LangGraph] Deployment correlation")
    tracer = state.get("_tracer")
    span = tracer.start_stage("deployment_correlation") if tracer else None
    try:
        state["deployments"] = investigate_deployments(state["incidents"])
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
    span = tracer.start_stage("log_retrieval") if tracer else None
    try:
        state["logs"] = investigate_logs(
            state["incidents"],
            state.get("keywords"),
            state.get("deployments"),
        )
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
    span = tracer.start_stage("runbook_retrieval") if tracer else None
    try:
        state["runbook"] = retrieve_runbook(state["question"], state["incidents"])
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
    state["bundle"] = EvidenceBundle(
        question=state["question"],
        incident_evidence=state.get("incidents", []),
        deployment_evidence=state.get("deployments", []),
        log_evidence=state.get("logs", []),
        runbook_evidence=state.get("runbook"),
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

def evidence_validation_node(state: RCAState) -> RCAState:
    """Validate the aggregated evidence and assess overall strength.

    Strength heuristic (based only on retrieval facts, never invention):
    - HIGH:   relevant incident (score >= 0.45) + deployment + ERROR/WARN logs
    - MEDIUM: relevant incident + at least one corroborating source
    - LOW:    incident only, or modest relevance
    - INSUFFICIENT: no relevant incident found
    """
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

    top_score = None
    if bundle.incident_evidence:
        scored = [
            i.relevance_score for i in bundle.incident_evidence
            if i.relevance_score is not None
        ]
        top_score = max(scored) if scored else None

    if not validation.incident_found:
        validation.evidence_strength = "INSUFFICIENT"
        notes.append("No relevant incident matched the question.")
    else:
        error_logs = [
            e for e in bundle.log_evidence
            if e.level in ("ERROR", "CRITICAL", "EXCEPTION")
        ]
        good_incident = top_score is not None and top_score >= 0.45
        corroboration = sum(
            [validation.deployment_found, bool(error_logs), validation.runbook_found]
        )
        if good_incident and validation.deployment_found and error_logs:
            validation.evidence_strength = "HIGH"
        elif corroboration >= 1:
            validation.evidence_strength = "MEDIUM"
        else:
            validation.evidence_strength = "LOW"
            notes.append("Incident match is not corroborated by deployments or logs.")
        if top_score is not None and top_score < 0.45:
            notes.append(
                f"Best incident relevance score is modest ({top_score:.2f})."
            )

    for err in meta.retrieval_errors:
        if err != "rca_generation":
            notes.append(f"Retrieval stage reported an issue: {err}.")

    validation.notes = notes
    state["validation"] = validation
    state["timeline"] = _build_timeline(bundle)
    logger.info(
        "Evidence validation: strength=%s incident=%s deployment=%s logs=%s runbook=%s",
        validation.evidence_strength, validation.incident_found,
        validation.deployment_found, validation.logs_found,
        validation.runbook_found,
    )
    return state

def rca_node(state: RCAState) -> RCAState:
    logger.info("[LangGraph] RCA generation")
    tracer = state.get("_tracer")
    span = tracer.start_stage("rca_generation") if tracer else None
    try:
        result = generate_gemini_rca(
            bundle=state["bundle"],
            validation=state["validation"],
            timeline=state.get("timeline", []),
            trace_span=span,
        )
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


graph = StateGraph(RCAState)
graph.add_node("question_analysis", question_analysis_node)
graph.add_node("incident_retrieval", incident_node)
graph.add_node("deployment_correlation", deployment_node)
graph.add_node("log_retrieval", log_node)
graph.add_node("runbook_retrieval", runbook_node)
graph.add_node("evidence_aggregation", evidence_aggregation_node)
graph.add_node("evidence_validation", evidence_validation_node)
graph.add_node("rca_generation", rca_node)

graph.set_entry_point("question_analysis")
graph.add_edge("question_analysis", "incident_retrieval")
graph.add_edge("incident_retrieval", "deployment_correlation")
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
    "deployment_correlation": "deployment_correlation",
    "log_retrieval": "log_retrieval",
    "runbook_retrieval": "runbook_retrieval",
    "evidence_aggregation": "evidence_aggregation",
    "evidence_validation": "evidence_validation",
    "rca_generation": "rca_generation",
}


def run_investigation(question: str, tracer: InvestigationTracer | None = None) -> dict:
    """Invoke the workflow with optional tracing; returns the final state."""
    return app.invoke({"question": question, "_tracer": tracer})


if __name__ == "__main__":
    import json

    result = run_investigation("Why is payroll failing?")
    print("\n========== STRUCTURED RCA ==========\n")
    print(json.dumps(result["investigation"], indent=2, default=str))

