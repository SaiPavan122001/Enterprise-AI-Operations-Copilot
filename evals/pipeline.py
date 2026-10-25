"""Runs test questions through the REAL copilot pipeline (LangGraph workflow,
retrieval + the configured LLM provider) and captures everything needed for
scoring and tracing.

Inside this eval process only, two wrappers are installed:
  * ``agents.gemini_rca_agent.generate_text`` (the single LLM seam) is wrapped
    to capture the exact prompt/response/token usage and (optionally) cache
    responses. Cache namespace = provider, key = (provider, configured model,
    exact prompt), so an answer is only reused for the same provider + model +
    prompt - never across providers. For Gemini the key format is unchanged
    from earlier runs, so cached Gemini answers stay valid when switching back.
  * the incident agent's ``search_incidents`` gets a lock so the embedded
    Qdrant client is not hit concurrently from worker threads.
The workflow is invoked with ``tracer=None``: evals create their own Langfuse
traces (see langfuse_io.py) with full inputs/outputs.
"""

import hashlib
import logging
import contextvars
import threading
import time

from evals.cache import get_cache, make_key
from evals.settings import load_config

logger = logging.getLogger(__name__)

# Mutable per-run slot; LangGraph copies contextvars into its worker threads,
# so the wrapper can write into the dict that run_question created.
_capture: contextvars.ContextVar[dict | None] = contextvars.ContextVar("capture", default=None)
_installed = False
_install_lock = threading.Lock()
_search_lock = threading.Lock()


class GenerationUsage:
    def __init__(self):
        self._lock = threading.Lock()
        self.calls = self.cached = self.input_tokens = self.output_tokens = 0

    def add(self, cached: bool, inp: int = 0, out: int = 0):
        with self._lock:
            self.calls += 1
            self.cached += int(cached)
            self.input_tokens += inp
            self.output_tokens += out


gen_usage = GenerationUsage()


def _record(purpose: str, capture: dict) -> None:
    """Store the capture of one LLM call under its purpose ("incident_match",
    "rca", ...) so several calls per question don't overwrite each other."""
    slot = _capture.get()
    if slot is not None:
        slot[purpose] = capture


def install_wrappers(use_cache: bool) -> None:
    """Idempotent and thread-safe. Wrapping twice would nest the search lock
    (a non-reentrant lock) inside itself and deadlock every worker."""
    with _install_lock:
        if not _installed:
            _install_wrappers(use_cache)


def _install_wrappers(use_cache: bool) -> None:
    global _installed
    import agents.gemini_rca_agent as rca_mod
    import agents.incident_agent as incident_mod

    original_search = incident_mod.search_incidents

    def locked_search(*args, **kwargs):
        with _search_lock:
            return original_search(*args, **kwargs)

    incident_mod.search_incidents = locked_search

    from agents.llm_client import LLMResponse
    from config import settings

    original_generate = rca_mod.generate_text
    cache = get_cache()

    def wrapped_generate(prompt: str, json_mode: bool = False, purpose: str = "rca",
                         temperature: float | None = None):
        provider, model = settings.LLM_PROVIDER, settings.llm_model
        # JSON-mode calls get a distinct key; plain calls keep the legacy key format.
        # Plain default-temperature calls keep the legacy key format; any call
        # option that changes the output is part of the key.
        if json_mode or temperature is not None:
            key = make_key(provider, model, prompt, {"json_mode": json_mode, "temperature": temperature})
        else:
            key = make_key(provider, model, prompt)
        started = time.perf_counter()
        if use_cache:
            hit = cache.get(provider, key)
            if hit is not None and hit.get("provider", provider) == provider:
                _record(purpose, {"provider": provider, "model": hit.get("model", model),
                         "prompt": prompt, "output": hit["text"],
                         "usage": hit.get("usage") or {}, "cached": True, "latency_ms": 0.0})
                gen_usage.add(True)
                return LLMResponse(text=hit["text"], provider=provider,
                                   model=hit.get("model", model), usage=hit.get("usage") or {})
        try:
            response = original_generate(prompt, json_mode=json_mode, purpose=purpose,
                                         temperature=temperature)
        except Exception as exc:
            _record(purpose, {"provider": provider, "model": model, "prompt": prompt,
                     "error": getattr(exc, "kind", "error"), "error_message": str(exc)[:300]})
            raise
        _record(purpose, {"provider": response.provider, "model": response.model, "prompt": prompt,
                 "output": response.text, "usage": response.usage, "cached": False,
                 "attempts": response.attempts,
                 "latency_ms": round((time.perf_counter() - started) * 1000, 1)})
        gen_usage.add(False, response.usage.get("input", 0), response.usage.get("output", 0))
        cache.set(provider, key, {"text": response.text, "usage": response.usage,
                                  "provider": response.provider, "model": response.model})
        return response

    rca_mod.generate_text = wrapped_generate
    _installed = True


def prompt_version() -> str:
    """Hash of every prompt that shapes an answer (RCA + evidence match)."""
    from agents.gemini_rca_agent import RCA_PROMPT
    from agents.incident_matcher import MATCH_PROMPT

    cfg_version = load_config()["langfuse"].get("prompt_version")
    digest = hashlib.sha1((RCA_PROMPT + "\n" + MATCH_PROMPT).encode("utf-8")).hexdigest()[:8]
    return cfg_version or "rca-" + digest


def pipeline_config() -> dict:
    """The knobs that define a run - used in the Langfuse run name/metadata."""
    from config import settings

    return {
        "embedding_model": "BAAI/bge-small-en-v1.5",   # backend/vector_store/search_service.py
        "chunking": "one-record-per-incident",
        "top_k": 5,                                     # backend/agents/incident_agent.py default
        "min_relevance_score": settings.MIN_RELEVANCE_SCORE,
        "relevance_margin": settings.RELEVANCE_MARGIN,
        "strong_relevance_score": settings.STRONG_RELEVANCE_SCORE,
        "evidence_match_check": "llm-same-problem-v1",
        "llm_provider": settings.LLM_PROVIDER,
        "llm_model": settings.llm_model,
        "prompt_version": prompt_version(),
        "llm_configured": bool(settings.llm_api_key),
    }


def _prompt_extras(state: dict) -> list[str]:
    """Non-retrieved prompt blocks the report may restate (strength, evidence
    notes, timeline) plus retrieved-but-not-matched incidents that policy
    answers name. Used for faithfulness only, not context precision/recall."""
    from agents import rca_structured as rs

    validation, bundle = state["validation"], state["bundle"]
    notes = "\n".join(f"- {n}" for n in rs.evidence_notes(validation)) or "- None."
    extras = [
        "EVIDENCE STRENGTH (computed by the application): " + validation.evidence_strength,
        "EVIDENCE NOTES:\n" + notes,
        "KNOWN TIMELINE:\n" + rs.format_timeline(state.get("timeline", [])),
    ]
    if bundle.related_incident_evidence:
        extras.append("RETRIEVED BUT NOT THE ASKED PROBLEM:\n" + "\n".join(
            f'[{i.incident_id}] service={i.service} | title="{i.title}" | recorded root cause: {i.root_cause}'
            for i in bundle.related_incident_evidence))
    return extras


def _contexts(bundle) -> list[str]:
    """Evidence given to the model, formatted exactly as in the production prompt."""
    from agents import rca_structured as rs

    contexts: list[str] = rs.format_incidents(bundle) + rs.format_deployments(bundle)
    if bundle.log_evidence:
        contexts.append("CORROBORATING LOG LINES:\n" + "\n".join(rs.format_logs(bundle)))
    if bundle.runbook_evidence:
        contexts.append("RUNBOOK GUIDANCE [RUNBOOK]:\n" + rs.format_runbook(bundle))
    return contexts


def core_answer(investigation: dict) -> str:
    parts = []
    if investigation.get("summary"):
        parts.append(investigation["summary"])
    if investigation.get("root_cause"):
        parts.append("Root cause: " + investigation["root_cause"])
    return "\n\n".join(parts) or (investigation.get("report_markdown") or "")


def _sections(investigation: dict, scalar: tuple, lists: tuple) -> str:
    parts = []
    for title, key in scalar:
        if investigation.get(key):
            parts.append(f"{title}: {investigation[key]}")
    for title, key in lists:
        if investigation.get(key):
            parts.append(f"{title}:\n" + "\n".join(f"- {x}" for x in investigation[key]))
    return "\n\n".join(parts) or core_answer(investigation)


def factual_answer(investigation: dict) -> str:
    """Sections presented as fact or evidence-backed conclusion (gated view):
    Summary, Impact, Root Cause, Evidence, Evidence-Backed Conclusions,
    Contributing Factors. Excludes labelled hypotheses, unknowns and advice."""
    return _sections(investigation,
                     (("Summary", "summary"), ("Impact", "impact"), ("Root Cause", "root_cause")),
                     (("Evidence", "observed_evidence"), ("Evidence-backed conclusions", "conclusions"),
                      ("Contributing factors", "contributing_factors")))


def factual_answer_legacy(investigation: dict) -> str:
    """The pre-change factual view (no conclusions section) - for comparability."""
    return _sections(investigation,
                     (("Summary", "summary"), ("Impact", "impact"), ("Root Cause", "root_cause")),
                     (("Evidence", "observed_evidence"), ("Contributing factors", "contributing_factors")))


def raw_core_answer(investigation: dict, rca_call: dict) -> str:
    """Summary exactly as the model wrote it (before caveat relocation) + the
    rendered root cause - scored separately so presentation rules can't hide
    answer-quality regressions."""
    import json as _json

    summary = investigation.get("summary") or ""
    if rca_call and rca_call.get("output"):
        try:
            summary = _json.loads(rca_call["output"]).get("summary") or summary
        except (ValueError, AttributeError):
            pass
    root = investigation.get("root_cause")
    return "\n\n".join(x for x in (summary, f"Root cause: {root}" if root else "") if x)


def run_question(question: str, use_cache: bool | None = None) -> dict:
    if use_cache is None:
        use_cache = load_config()["generation"]["cache_generation"]
    install_wrappers(use_cache)
    from security.access import system_principal
    from workflows.rca_graph import run_investigation

    slot: dict = {}
    _capture.set(slot)
    started = time.perf_counter()
    # Explicit trusted identity for the local harness (default tenant, all its services).
    state = run_investigation(question, tracer=None, principal=system_principal("eval-harness"))
    latency = round((time.perf_counter() - started) * 1000, 1)
    inv = state["investigation"]
    bundle = state["bundle"]
    rca_call = slot.get("rca") or {}
    match_call = slot.get("incident_match") or {}
    source = inv.get("answer_source")
    return {
        "question": question,
        "status": inv.get("status"),
        "evidence_strength": inv.get("evidence_strength"),
        "confidence": inv.get("confidence"),
        "answer_status": inv.get("answer_status"),
        # llm = validated model answer; policy = deterministic evidence-policy answer
        # (no matched incident); fallback = LLM failed. llm and policy are genuine answers.
        "answer_source": source,
        # "guardrail" = declined by the input rails: a defined answer (judged as a refusal), not a fallback -
        # unless the rails could not run (guardrail_unavailable), which is a failure like an LLM fallback
        "answered": source in ("llm", "policy", "analytics") or (
            source == "guardrail" and (state.get("blocked") or {}).get("category") != "guardrail_unavailable"),
        "candidate_ids": [i.incident_id for i in bundle.incident_evidence]
                         + [i.incident_id for i in bundle.related_incident_evidence],
        "incident_ids": [i.incident_id for i in bundle.incident_evidence],          # matched
        "related_incident_ids": [i.incident_id for i in bundle.related_incident_evidence],
        "match_assessments": bundle.match_assessments,
        "match_available": bundle.match_available,
        "question_scope": bundle.question_scope,
        "incident_scores": [i.relevance_score for i in bundle.incident_evidence],
        "deployment_ids": [d.deployment_id for d in bundle.deployment_evidence],
        "link_notes": bundle.link_notes,
        "missing_evidence": state["validation"].missing_evidence,
        "contradictions": state["validation"].contradictions,
        "runbook": bundle.runbook_evidence.name if bundle.runbook_evidence else None,
        "log_count": len(bundle.log_evidence),
        "contexts": _contexts(bundle),
        "prompt_contexts": _contexts(bundle) + _prompt_extras(state),
        "answer_full": inv.get("report_markdown") or "",
        "answer_core": core_answer(inv),
        "answer_core_raw": raw_core_answer(inv, rca_call),
        "answer_factual": factual_answer(inv),
        "answer_factual_legacy": factual_answer_legacy(inv),
        "grounding_issues": inv.get("grounding_issues") or [],
        # Captured LLM calls (None when not made / failed).
        "generation": rca_call if rca_call.get("output") else None,
        "match_generation": match_call if match_call.get("output") else None,
        "generation_error": inv.get("generation_error")
                            or (rca_call.get("error") if rca_call and not rca_call.get("output") else None),
        "generation_error_message": rca_call.get("error_message"),
        "generation_provider": inv.get("generation_provider"),
        "generation_model": inv.get("generation_model"),
        "retrieval_errors": bundle.retrieval_metadata.retrieval_errors,
        "latency_ms": latency,
    }
