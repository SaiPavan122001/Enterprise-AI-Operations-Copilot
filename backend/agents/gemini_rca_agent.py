"""LLM-powered RCA generation over the structured evidence layer.

The provider is selected by configuration (``LLM_PROVIDER=gemini|openai``);
the module keeps its historical name so imports and patches stay stable.

Receives an :class:`~models.evidence.EvidenceBundle` (matched incidents
only) plus the :class:`~models.evidence.EvidenceValidation` verdict and
produces an :class:`~models.evidence.InvestigationResult`:

* no matched incident / unsupported question -> evidence-policy answer
  (``rca_structured.policy_answer``), no cause is requested from the model;
* otherwise the model returns evidence-cited JSON, which is validated by
  deterministic grounding checks (``rca_structured.validate``) and rendered.

The evidence layer is authoritative for confidence. Failures are logged
internally; users never see raw exceptions.
"""

import json
import logging
import re
import time
from typing import Any

from google import genai

from agents import rca_structured as rs
from agents.llm_client import (
    LLMConfigError,
    LLMError,
    LLMResponse,
    call_with_retry,
)
from config import settings
from models.evidence import (
    EvidenceBundle,
    EvidenceValidation,
    InvestigationResult,
    TimelineEvent,
)

logger = logging.getLogger(__name__)

CONFIDENCE_RANK = rs.CONFIDENCE_RANK
MAX_INCIDENTS = 5      # used by the evidence-only fallback report
MAX_DEPLOYMENTS = 5

# The prompt template (its hash is the prompt version recorded by evaluations).
RCA_PROMPT = rs.STRUCTURED_PROMPT


def _format_incidents(bundle: EvidenceBundle) -> str:
    return "\n".join(rs.format_incidents(bundle)) or "- None."


def _format_deployments(bundle: EvidenceBundle) -> str:
    return "\n".join(rs.format_deployments(bundle)) or "- No verified deployment links."


def _format_logs(bundle: EvidenceBundle) -> str:
    return "\n".join(rs.format_logs(bundle)) or "- No log lines corroborate the matched incidents."


def _format_timeline(timeline: list[TimelineEvent]) -> str:
    return rs.format_timeline(timeline)


def _format_runbook(bundle: EvidenceBundle) -> str:
    return rs.format_runbook(bundle)


def _extract_confidence(report: str) -> str:
    match = re.search(
        r"##\s*Confidence\s*\n+.*?(High|Medium|Low|Insufficient)",
        report,
        re.IGNORECASE | re.DOTALL,
    )
    return match.group(1).upper() if match else "MEDIUM"


def _extract_section(report: str, title: str) -> str:
    match = re.search(
        rf"##\s*{re.escape(title)}\s*\n(.*?)(?=\n##\s|\Z)",
        report,
        re.IGNORECASE | re.DOTALL,
    )
    return match.group(1).strip() if match else ""


def _extract_list(report: str, title: str) -> list[str]:
    body = _extract_section(report, title)
    items: list[str] = []
    for line in body.splitlines():
        cleaned = re.sub(r"^(\s*[-*]\s*|\s*\d+[.)]\s*)", "", line).strip()
        if cleaned:
            items.append(cleaned)
    return items


def _final_confidence(model_confidence: str, validation: EvidenceValidation) -> str:
    """The evidence layer is authoritative: the model can never report a
    confidence level higher than the assessed evidence strength."""
    model_rank = CONFIDENCE_RANK.get(model_confidence, 1)
    evidence_rank = CONFIDENCE_RANK[validation.evidence_strength]
    final_rank = min(model_rank, evidence_rank)
    for name, rank in CONFIDENCE_RANK.items():
        if rank == final_rank:
            return name
    return "LOW"


def _build_result(
    bundle: EvidenceBundle,
    validation: EvidenceValidation,
    timeline: list[TimelineEvent],
    clean: dict,
    source: str,
    issues: list[str] | None = None,
    llm: LLMResponse | None = None,
) -> InvestigationResult:
    """Build the API result from a validated structured answer."""
    return InvestigationResult(
        question=bundle.question,
        status="success",
        summary=clean["summary"] or None,
        impact="\n".join(rs.claims_text(clean, "impact")) or "Not recorded in the available evidence.",
        root_cause=rs.root_cause_text(clean),
        confidence=clean["confidence"],
        evidence_strength=validation.evidence_strength,
        contributing_factors=rs.claims_text(clean, "contributing_factors"),
        recommended_remediation=clean["recommended_remediation"],
        preventive_actions=clean["preventive_actions"],
        observed_evidence=rs.claims_text(clean, "confirmed_facts"),
        investigation_details=rs.investigation_details(bundle, clean),
        timeline=timeline,
        evidence=bundle,
        validation=validation,
        report_markdown=rs.render_markdown(clean, bundle),
        message=None,
        generation_provider=llm.provider if llm else None,
        generation_model=llm.model if llm else None,
        answer_status=clean["answer_status"],
        answer_source=source,
        conclusions=rs.claims_text(clean, "conclusions"),
        hypotheses=rs.claims_text(clean, "hypotheses"),
        unknowns=clean["unknowns"],
        grounding_issues=issues or [],
        per_incident_findings=rs.claims_text(clean, "per_incident"),
        incident_relationship=rs.relationship_text(clean),
    )


FALLBACK_MESSAGES = {
    "config": "AI analysis is unavailable because the AI model or API key is misconfigured.",
    "quota_exhausted": "AI analysis is unavailable because the AI provider quota is exhausted.",
}


def _fallback_result(
    bundle: EvidenceBundle,
    validation: EvidenceValidation,
    timeline: list[TimelineEvent],
    error_kind: str = "error",
) -> InvestigationResult:
    """Evidence-only result used when the LLM is unavailable. Contains zero
    AI inference - only retrieved facts and runbook guidance."""
    observed: list[str] = []
    for i in bundle.incident_evidence[:MAX_INCIDENTS]:
        observed.append(
            f"Incident {i.incident_id} ({i.service}): {i.title} - "
            f"known root cause on record: {i.root_cause}"
        )
    for d in bundle.deployment_evidence[:MAX_DEPLOYMENTS]:
        observed.append(
            f"Deployment {d.deployment_id} on {d.service} at {d.time}: {d.change}"
        )
    error_logs = [
        e for e in bundle.log_evidence if e.level in ("ERROR", "CRITICAL", "WARN")
    ]
    for e in error_logs[:10]:
        observed.append(f"Log {e.level} on {e.service} at {e.timestamp}: {e.message}")

    remediation = (
        [
            re.sub(r"^\s*\d+[.)]\s*", "", line).strip()
            for line in bundle.runbook_evidence.content.splitlines()
            if re.match(r"^\s*\d+[.)]\s", line)
        ]
        if bundle.runbook_evidence
        else ["No runbook guidance matched; review deployments and logs manually."]
    )

    summary = (
        f"{len(bundle.incident_evidence)} relevant incident(s), "
        f"{len(bundle.deployment_evidence)} correlated deployment(s) and "
        f"{len(bundle.log_evidence)} relevant log entries were retrieved. "
        "The AI reasoning engine is temporarily unavailable, so no automated "
        "root cause inference was performed - the observed evidence is listed "
        "below for manual review."
        if observed else
        "No relevant enterprise evidence was found for this question, and the "
        "AI reasoning engine is temporarily unavailable."
    )

    markdown = f"""# Root Cause Analysis

## Summary
{summary}

## Impact
{len(bundle.incident_evidence)} matching incident(s) found in the enterprise data.

## Evidence
{chr(10).join(f'- {item}' for item in observed) or '- No observed evidence found.'}

## Root Cause
Not determined - automated analysis is currently unavailable.

## Contributing Factors
- Unknown pending full analysis.

## Recommended Remediation
{chr(10).join(f'{n}. {item}' for n, item in enumerate(remediation, 1))}

## Preventive Actions
1. To be defined after a full root cause analysis.

## Confidence
Low - generated without AI reasoning.

## Investigation Details
Incidents: {len(bundle.incident_evidence)} | Deployments: {len(bundle.deployment_evidence)} | Log entries: {len(bundle.log_evidence)} | Runbook: {bundle.runbook_evidence.title if bundle.runbook_evidence else 'none'}
"""  # noqa: E501

    return InvestigationResult(
        question=bundle.question,
        status="error",
        summary=summary,
        impact=(
            f"{len(bundle.incident_evidence)} matching incident(s) found."
            if bundle.incident_evidence else None
        ),
        root_cause=None,
        confidence="LOW" if validation.evidence_strength != "INSUFFICIENT" else "INSUFFICIENT",
        evidence_strength=validation.evidence_strength,
        contributing_factors=[],
        recommended_remediation=remediation,
        preventive_actions=[],
        observed_evidence=observed,
        investigation_details=None,
        timeline=timeline,
        evidence=bundle,
        validation=validation,
        report_markdown=markdown,
        message=(
            FALLBACK_MESSAGES.get(error_kind, "AI analysis is temporarily unavailable.")
            + " The observed evidence is included below; no AI inference was performed."
        ),
        generation_provider=settings.LLM_PROVIDER,
        generation_model=settings.llm_model,
        generation_error=error_kind,
        answer_source="fallback",
    )



# --------------------------------------------------------------------------- providers

def _call_gemini(prompt: str, json_mode: bool = False, temperature: float | None = None) -> LLMResponse:
    kwargs: dict[str, Any] = {"model": settings.GEMINI_MODEL, "contents": prompt}
    config: dict[str, Any] = {}
    if json_mode:
        config["response_mime_type"] = "application/json"
    if temperature is not None:
        config["temperature"] = temperature
    if config:
        kwargs["config"] = config
    response = client.models.generate_content(**kwargs)
    text = response.text
    if not text:
        raise LLMError("Gemini returned an empty response", provider="gemini")
    meta = getattr(response, "usage_metadata", None)
    usage = {
        "input": getattr(meta, "prompt_token_count", None) or 0,
        "output": (getattr(meta, "candidates_token_count", None) or 0)
                  + (getattr(meta, "thoughts_token_count", None) or 0),
    }
    return LLMResponse(text=text, provider="gemini", model=settings.GEMINI_MODEL, usage=usage)


_openai_client = None


def _openai():
    global _openai_client
    if _openai_client is None:
        from openai import OpenAI

        # max_retries=0: retries are handled (with backoff) by call_with_retry.
        _openai_client = OpenAI(
            api_key=settings.OPENAI_API_KEY,
            timeout=settings.OPENAI_TIMEOUT_MS / 1000,
            max_retries=0,
        )
    return _openai_client


def _call_openai(prompt: str, json_mode: bool = False, temperature: float | None = None) -> LLMResponse:
    kwargs: dict[str, Any] = {"model": settings.OPENAI_MODEL, "messages": [{"role": "user", "content": prompt}]}
    if temperature is not None:
        kwargs["temperature"] = temperature
    if json_mode:
        # JSON mode requires the word "JSON" in the prompt (all JSON prompts include it).
        kwargs["response_format"] = {"type": "json_object"}
    response = _openai().chat.completions.create(**kwargs)
    text = response.choices[0].message.content if response.choices else None
    if not text:
        raise LLMError("OpenAI returned an empty response", provider="openai")
    usage = {
        "input": getattr(response.usage, "prompt_tokens", 0) or 0,
        "output": getattr(response.usage, "completion_tokens", 0) or 0,
    }
    return LLMResponse(text=text, provider="openai",
                       model=response.model or settings.OPENAI_MODEL, usage=usage)


PROVIDERS = {"gemini": _call_gemini, "openai": _call_openai}


def generate_text(prompt: str, json_mode: bool = False, purpose: str = "rca",
                  temperature: float | None = None) -> LLMResponse:
    """Single seam for LLM text generation (provider from configuration).
    ``purpose`` labels the call (e.g. "incident_match", "rca") for tracing/caching."""
    provider = settings.LLM_PROVIDER
    if provider not in PROVIDERS:
        raise LLMConfigError(f"Unsupported LLM_PROVIDER={provider!r}", provider=provider)
    if not settings.llm_api_key:
        raise LLMConfigError(f"{provider.upper()}_API_KEY is not set", provider=provider)
    start, outcome, attempts = time.perf_counter(), "error", None
    try:
        response = call_with_retry(
            lambda: PROVIDERS[provider](prompt, json_mode, temperature),
            provider=provider,
            max_retries=settings.llm_max_retries,
            base=settings.LLM_BACKOFF_BASE_SECONDS,
            cap=settings.LLM_BACKOFF_MAX_SECONDS,
            quota_cooldown=settings.LLM_QUOTA_COOLDOWN_SECONDS,
        )
        outcome, attempts = "ok", response.attempts
        return response
    except LLMError as err:
        outcome = err.kind
        raise
    except BaseException:
        outcome = "cancelled"
        raise
    finally:
        # One line per LLM call: no prompt or answer text is logged.
        logger.info("LLM call %s %s", purpose, outcome,
                    extra={"provider": provider, "model": settings.llm_model, "purpose": purpose,
                           "outcome": outcome, "attempts": attempts,
                           "duration_ms": round((time.perf_counter() - start) * 1000)})


def _trace_generation(trace_span, *, model: str, provider: str, usage: dict | None,
                      attempts: int | None, error: str | None) -> None:
    """Record the LLM call on the stage span. Prompt/answer are not recorded
    (production traces deliberately avoid storing enterprise data)."""
    if trace_span is None:
        return
    try:
        gen = trace_span.start_observation(
            name="llm-generation", as_type="generation", model=model,
            usage_details=usage or None,
            metadata={"provider": provider, "attempts": attempts, "error": error},
            level="ERROR" if error else None,
            status_message=error,
        )
        gen.end()
    except Exception:
        logger.warning("Langfuse generation record failed (non-fatal)")


def _generate_structured(prompt: str) -> tuple[dict, LLMResponse]:
    """Call the model for JSON; one retry if the output is not valid JSON."""
    last_error = None
    for _ in range(2):
        llm = generate_text(prompt, json_mode=True, purpose="rca", temperature=0.2)
        try:
            return rs.parse_json(llm.text), llm
        except (ValueError, json.JSONDecodeError) as exc:
            last_error = exc
            logger.warning("RCA output was not valid JSON - retrying once")
    raise LLMError(f"invalid structured output: {last_error}", provider=settings.LLM_PROVIDER)


def generate_gemini_rca(
    bundle: EvidenceBundle,
    validation: EvidenceValidation,
    timeline: list[TimelineEvent],
    trace_span=None,
) -> InvestigationResult:
    """Generate the structured RCA. Never raises - always returns an
    ``InvestigationResult``:
      answer_source="policy"   no matched incident / unsupported question
      answer_source="llm"      validated, evidence-cited model answer
      answer_source="fallback" the LLM call failed (evidence-only report,
                               ``generation_error`` set; never a model answer)
    """
    if not bundle.incident_evidence:
        kind = "out_of_scope" if bundle.question_scope == "general" else "insufficient_evidence"
        logger.info("Evidence policy answer (%s): no matched incident", kind)
        return _build_result(bundle, validation, timeline, rs.policy_answer(bundle, validation, kind),
                             source="policy")

    prompt = rs.build_prompt(bundle, validation, timeline)
    logger.debug("RCA prompt built (length=%d chars)", len(prompt))
    logger.info("Calling %s (%s)", settings.LLM_PROVIDER, settings.llm_model)
    try:
        data, llm = _generate_structured(prompt)
    except LLMError as err:
        _trace_generation(trace_span, model=settings.llm_model, provider=settings.LLM_PROVIDER,
                          usage=None, attempts=None, error=err.kind)
        logger.error("RCA generation failed (%s) - returning evidence-only report", err.kind)
        return _fallback_result(bundle, validation, timeline, error_kind=err.kind)
    except Exception:
        logger.exception("RCA generation failed unexpectedly")
        _trace_generation(trace_span, model=settings.llm_model, provider=settings.LLM_PROVIDER,
                          usage=None, attempts=None, error="error")
        return _fallback_result(bundle, validation, timeline, error_kind="error")

    clean, issues = rs.validate(data, bundle, validation, timeline)
    # Output rails (NeMo) + PII redaction run AFTER citation validation, claim
    # verification and causal guards - they add protection, they replace none.
    clean, guard_events = protect_output(clean, bundle, validation)
    issues = issues + guard_events
    # Log what the checks did, not the claim text (answer content stays out of logs;
    # the full issues are returned in the result's grounding_issues).
    for issue in issues:
        logger.info("Grounding check: %s", ": ".join(issue.split(" - ")[0].split(": ")[:2]))
    _trace_generation(trace_span, model=llm.model, provider=llm.provider, usage=llm.usage,
                      attempts=llm.attempts, error=None)
    logger.info("RCA generated by %s:%s (%s, %d grounding issue(s))",
                llm.provider, llm.model, clean["answer_status"], len(issues))
    result = _build_result(bundle, validation, timeline, clean, source="llm", issues=issues, llm=llm)
    result.guardrail_events = [e for e in guard_events]
    return result


def evidence_text(bundle: EvidenceBundle, validation: EvidenceValidation) -> str:
    """All authorized evidence text (already passed through the retrieval rail)."""
    parts = [f"{i.incident_id} {i.service} {i.severity} {i.status} {i.title} {i.root_cause}"
             for i in bundle.incident_evidence]
    parts += [f"{d.deployment_id} {d.service} {d.time} {d.change}" for d in bundle.deployment_evidence]
    parts += [f"{e.timestamp} {e.service} {e.level} {e.message}" for e in bundle.log_evidence]
    if bundle.runbook_evidence:
        parts.append(f"{bundle.runbook_evidence.title} {bundle.runbook_evidence.content}")
    parts += rs.evidence_notes(validation)
    return "\n".join(parts)


def protect_output(clean: dict, bundle: EvidenceBundle, validation: EvidenceValidation) -> tuple[dict, list[str]]:
    """PII redaction of every answer string (values that occur in the authorized
    evidence are kept), then the output rail (unsafe advice, links, commands,
    credential requests, exfiltration instructions). Redacting first means a
    sentence that merely mentions personal data is kept with a placeholder instead
    of being removed."""
    from security import guardrails, pii

    evidence = evidence_text(bundle, validation)
    keep = pii.evidence_keep_set([evidence])
    before = json.dumps(clean, default=str, sort_keys=True)
    clean = pii.redact_payload(clean, keep)
    events = []
    if json.dumps(clean, default=str, sort_keys=True) != before:
        events.append("pii: personal data or secrets redacted from the answer")
    sections = {k: v for k, v in clean.items() if not k.startswith("_")}
    # Links / e-mail addresses only from the runbook (records never contain any;
    # one planted in an incident, deployment or log must not reach the user).
    runbook = bundle.runbook_evidence.content if bundle.runbook_evidence else ""
    sections, removed = guardrails.sanitize_output(sections, evidence, links_from=runbook)
    clean = {**clean, **sections}
    events += [f"output rail: {r}" for r in removed]
    return clean, events


GUARDRAIL_MESSAGES = {
    "prompt_injection": "it tries to change the copilot's instructions or dictate the answer",
    "action_request": "it asks the copilot to act on systems; consequential actions go through the approval workflow",
    "sensitive_data_request": "it asks for credentials, secrets or personal data",
    "guardrail_unavailable": "the safety checks could not be completed, so it was not processed (try again later)",
}


def guardrail_refusal(bundle: EvidenceBundle, validation: EvidenceValidation, blocked: dict) -> InvestigationResult:
    """Answer for a request the input rails declined: no retrieval, no generation."""
    category = str(blocked.get("category") or "policy")
    why = GUARDRAIL_MESSAGES.get(category, "it does not comply with the copilot's usage policy")
    clean = {
        "answer_status": "blocked", "confirmed_facts": [], "conclusions": [], "hypotheses": [], "impact": [],
        "contributing_factors": [], "recommended_remediation": [], "preventive_actions": [],
        "summary": (f"This request was declined by the input guardrails because {why}. Ask a question about "
                    "an incident, its cause, deployments, logs or runbooks."),
        "root_cause": {"status": "not_determined", "statement": "", "refs": []},
        "unknowns": [f"Guardrail category: {category}."],
        "confidence": "INSUFFICIENT", "confidence_reason": "The request was declined before retrieval.",
    }
    return _build_result(bundle, validation, [], clean, source="guardrail")


def gemini_http_options() -> dict:
    # google-genai 0.6.x takes the request timeout in SECONDS (passed to
    # requests); GEMINI_TIMEOUT_MS is milliseconds. Passing the ms value
    # directly made the timeout 1000x too long (60000 s).
    return {"timeout": settings.GEMINI_TIMEOUT_MS / 1000}


client = genai.Client(
    api_key=settings.GEMINI_API_KEY or "missing-gemini-api-key",
    http_options=gemini_http_options(),
)
