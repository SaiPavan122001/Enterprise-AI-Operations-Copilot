"""Gemini-powered RCA generation over the structured evidence layer.

Receives an :class:`~models.evidence.EvidenceBundle` plus the
:class:`~models.evidence.EvidenceValidation` verdict, builds a grounded
structured prompt, and parses the response into an
:class:`~models.evidence.InvestigationResult`.

The evidence layer is authoritative for confidence: if validation says the
evidence is LOW or INSUFFICIENT, Gemini cannot upgrade the reported
confidence. Failures are logged internally; users never see raw exceptions.
"""

import logging
import re

from google import genai

from config import settings
from models.evidence import (
    EvidenceBundle,
    EvidenceValidation,
    InvestigationResult,
    TimelineEvent,
)
from observability.langfuse_client import langfuse

logger = logging.getLogger(__name__)

MAX_INCIDENTS = 5
MAX_DEPLOYMENTS = 5
MAX_LOGS = 30
MAX_RUNBOOK_CHARS = 3000

CONFIDENCE_RANK = {"INSUFFICIENT": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3}

RCA_PROMPT = """You are a Senior Site Reliability Engineer performing a root cause analysis.

USER QUESTION:
{question}

EVIDENCE STRENGTH (assessed by the retrieval pipeline, independent of your analysis): {evidence_strength}

OBSERVED EVIDENCE (retrieved from enterprise systems - these are FACTS):

MATCHED INCIDENTS:
{incidents}

RELATED DEPLOYMENTS (correlated by deployment_id):
{deployments}

RELEVANT LOG ENTRIES (source: logs.txt):
{logs}

KNOWN TIMELINE (derived only from real timestamps in the data above):
{timeline}

RUNBOOK GUIDANCE (internal operational documentation - advisory guidance only, NOT evidence that the documented failure occurred):
{runbook}

INSTRUCTIONS:
1. Use ONLY the evidence above. Never invent incidents, deployments, logs, metrics, or timestamps.
2. Clearly distinguish observed facts from your own inference.
3. If the evidence strength is LOW or INSUFFICIENT, explicitly say the RCA is inconclusive and explain what additional data is needed.
4. Use runbooks for remediation guidance only; do not present runbook content as observed evidence.
5. Identify the affected service and the related deployment (with ID) when known.
6. Explain WHY the selected root cause was chosen over alternatives.
7. In the Confidence section, state exactly one of: High, Medium, or Low, with one sentence of justification. Do not claim High if the evidence strength is LOW or INSUFFICIENT.

Respond in Markdown using EXACTLY this structure:

# Root Cause Analysis

## Summary
One short paragraph describing what happened and the likely cause.

## Impact
Which services and users were affected, and how.

## Evidence
Bulleted observed facts from the incidents, deployments and logs above.

## Root Cause
The most likely root cause, with the specific evidence supporting it.

## Contributing Factors
Bulleted list; one factor per line starting with "- ". Write "None identified" if none.

## Recommended Remediation
Numbered, concrete steps (use the runbook guidance where relevant).

## Preventive Actions
Numbered actions to prevent recurrence.

## Confidence
High | Medium | Low - with one sentence of justification.

## Investigation Details
Briefly list which incidents, deployments, log patterns and runbooks were used.
"""


def _format_incidents(bundle: EvidenceBundle) -> str:
    if not bundle.incident_evidence:
        return "- No relevant incidents were found (retrieval threshold not met)."
    lines = []
    for i in bundle.incident_evidence[:MAX_INCIDENTS]:
        lines.append(
            f"- Incident {i.incident_id} | service={i.service} | "
            f"severity={i.severity} | status={i.status} | "
            f"title=\"{i.title}\" | known root cause: {i.root_cause} | "
            f"relevance={i.relevance_score:.2f}" if i.relevance_score is not None else
            f"- Incident {i.incident_id} | service={i.service} | severity={i.severity} | "
            f"status={i.status} | title=\"{i.title}\" | known root cause: {i.root_cause}"
        )
    return "\n".join(lines)



def _format_deployments(bundle: EvidenceBundle) -> str:
    if not bundle.deployment_evidence:
        return "- No deployments could be correlated to the matched incidents."
    return "\n".join(
        f"- Deployment {d.deployment_id} | service={d.service} | "
        f"time={d.time} | change=\"{d.change}\""
        for d in bundle.deployment_evidence[:MAX_DEPLOYMENTS]
    )


def _format_logs(bundle: EvidenceBundle) -> str:
    if not bundle.log_evidence:
        return "- No relevant log entries were found."
    return "\n".join(
        f"  {e.timestamp or 'ts-unknown'} {e.service or 'unknown-service'} "
        f"{e.level or 'LOG'}: {e.message}"
        for e in bundle.log_evidence[:MAX_LOGS]
    )


def _format_timeline(timeline: list[TimelineEvent]) -> str:
    if not timeline:
        return "- No reliable timestamps were available; no timeline can be constructed."
    return "\n".join(f"- {e.timestamp} - {e.event} (source: {e.source})" for e in timeline)


def _format_runbook(bundle: EvidenceBundle) -> str:
    runbook = bundle.runbook_evidence
    if not runbook:
        return "- No runbook matched this investigation."
    return (
        f"Runbook: {runbook.title} (source: {runbook.name})\n"
        f"{runbook.content[:MAX_RUNBOOK_CHARS]}"
    )


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
    question: str,
    bundle: EvidenceBundle,
    validation: EvidenceValidation,
    timeline: list[TimelineEvent],
    report: str,
    status: str,
    message: str | None,
) -> InvestigationResult:
    model_confidence = _extract_confidence(report)
    return InvestigationResult(
        question=question,
        status="success" if status == "success" else "error",
        summary=_extract_section(report, "Summary") or None,
        impact=_extract_section(report, "Impact") or None,
        root_cause=_extract_section(report, "Root Cause") or None,
        confidence=_final_confidence(model_confidence, validation),
        evidence_strength=validation.evidence_strength,
        contributing_factors=_extract_list(report, "Contributing Factors"),
        recommended_remediation=_extract_list(report, "Recommended Remediation"),
        preventive_actions=_extract_list(report, "Preventive Actions"),
        observed_evidence=_extract_list(report, "Evidence"),
        investigation_details=_extract_section(report, "Investigation Details") or None,
        timeline=timeline,
        evidence=bundle,
        validation=validation,
        report_markdown=report,
        message=message,
    )


def _fallback_result(
    bundle: EvidenceBundle,
    validation: EvidenceValidation,
    timeline: list[TimelineEvent],
) -> InvestigationResult:
    """Evidence-only result used when Gemini is unavailable. Contains zero
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
"""

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
            "AI analysis is temporarily unavailable. The observed evidence is "
            "included below; no AI inference was performed."
        ),
    )



def generate_gemini_rca(
    bundle: EvidenceBundle,
    validation: EvidenceValidation,
    timeline: list[TimelineEvent],
    trace_span=None,
) -> InvestigationResult:
    """Generate the structured RCA. Never raises - always returns an
    ``InvestigationResult`` (status ``error`` with evidence-only content on
    unrecoverable failure)."""
    prompt = RCA_PROMPT.format(
        question=bundle.question.strip(),
        evidence_strength=validation.evidence_strength,
        incidents=_format_incidents(bundle),
        deployments=_format_deployments(bundle),
        logs=_format_logs(bundle),
        timeline=_format_timeline(timeline),
        runbook=_format_runbook(bundle),
    )
    logger.debug("RCA prompt built (length=%d chars)", len(prompt))

    attempts = settings.GEMINI_MAX_RETRIES + 1
    for attempt in range(1, attempts + 1):
        try:
            logger.info(
                "Calling Gemini (%s), attempt %d/%d",
                settings.GEMINI_MODEL, attempt, attempts,
            )
            try:
                if trace_span:
                    trace_span.event(
                        name="gemini-call",
                        metadata={"attempt": attempt, "model": settings.GEMINI_MODEL},
                    )
            except Exception:
                logger.warning("Langfuse span event failed (non-fatal)")

            response = client.models.generate_content(
                model=settings.GEMINI_MODEL,
                contents=prompt,
            )
            report = response.text

            try:
                if trace_span:
                    trace_span.end()
                langfuse.flush()
            except Exception:
                logger.warning("Langfuse span close failed (non-fatal)")

            logger.info("Gemini RCA generated successfully")
            return _build_result(
                question=bundle.question,
                bundle=bundle,
                validation=validation,
                timeline=timeline,
                report=report,
                status="success",
                message=None,
            )

        except Exception:
            # Full technical detail stays in internal logs only.
            logger.exception(
                "Gemini RCA generation failed (attempt %d/%d)", attempt, attempts
            )

    logger.error("Gemini RCA failed after %d attempts", attempts)
    return _fallback_result(bundle, validation, timeline)


client = genai.Client(
    api_key=settings.GEMINI_API_KEY or "missing-gemini-api-key",
    http_options={"timeout": settings.GEMINI_TIMEOUT_MS},
)
