"""PII and secret protection: detection, evidence preservation, and the places
data must not leak (LLM prompts, logs, rejected requests, responses)."""

import json
import logging

import pytest

from security import pii

SAMPLES = {
    "PERSON": "Why can't Jane Doe log in to the auth-service?",
    "EMAIL_ADDRESS": "jane.doe@acme-corp.com cannot log in",
    "PHONE_NUMBER": "call the on-call at +1 415-555-0142 about payroll",
    "CREDENTIAL": "payroll fails with password=Hunter2!Secret",
    "API_KEY": "the job used key sk-" + "proj-abcdefghijklmnopqrstuv",
    "EMPLOYEE_ID": "employee ID 44718 sees wrong leave balance",
    "US_SSN": "SSN 123-45-6789 appears in the export",
    "CREDIT_CARD": "card 4111 1111 1111 1111 was charged twice",
}


@pytest.mark.parametrize("entity,text", [(k, v) for k, v in SAMPLES.items() if k != "PERSON"])
def test_regex_engine_redacts_structured_pii_and_secrets(entity, text):
    out = pii.redact_text(text)
    assert f"<{entity}>" in out, out


@pytest.mark.presidio
@pytest.mark.parametrize("entity,text", list(SAMPLES.items()))
def test_presidio_redacts_names_pii_and_secrets(entity, text):
    out = pii.redact_text(text)
    assert f"<{entity}>" in out, out


@pytest.mark.presidio
@pytest.mark.parametrize("text", [
    "Why are users unable to login to the auth-service since 2026-05-03 10:06?",
    "INC-014 dashboard metrics incorrect after DEP-114 on reporting-service",
    "Elasticsearch index corruption on employee-service; host 10.0.0.12 timed out",
    "## Root Cause\nBatch job executed twice [INC-009]",
])
def test_investigation_evidence_is_not_redacted(text):
    assert pii.redact_text(text) == text


def test_values_present_in_authorized_evidence_are_kept():
    keep = pii.evidence_keep_set(["Runbook: page the on-call at oncall@corp.example"])
    out = pii.redact_text("Contact oncall@corp.example and jane@evil.example", keep)
    assert "oncall@corp.example" in out and "<EMAIL_ADDRESS>" in out


def test_off_engine_changes_nothing(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "PII_ENGINE", "off")
    assert pii.redact_text(SAMPLES["EMAIL_ADDRESS"]) == SAMPLES["EMAIL_ADDRESS"]


def test_question_is_redacted_before_any_llm_call(monkeypatch):
    """The prompt the LLM receives never contains the e-mail / credential."""
    from agents import gemini_rca_agent
    from agents.llm_client import LLMResponse
    from security.access import system_principal
    from workflows import rca_graph

    prompts = []

    def fake(prompt, **k):
        prompts.append(prompt)
        return LLMResponse(text=json.dumps({"question_scope": "incident_investigation", "assessments": []}),
                           provider="openai", model="m")

    monkeypatch.setattr(gemini_rca_agent, "generate_text", fake)
    q = "Why can't jane.doe@acme-corp.com log in with password=Hunter2!Secret on the auth-service?"
    state = rca_graph.run_investigation(q, principal=system_principal("t"))
    assert prompts and all("jane.doe" not in p and "Hunter2" not in p for p in prompts)
    assert "<EMAIL_ADDRESS>" in state["investigation"]["question"]


def test_log_lines_redact_pii():
    from utils.log_context import redact
    out = redact("user jane.doe@acme-corp.com phone 415-555-0142 password=abc123 employee id 44718")
    assert "jane.doe" not in out and "415-555" not in out and "abc123" not in out and "44718" not in out


def test_rejected_request_input_is_not_logged(caplog):
    from fastapi.testclient import TestClient

    from app import app
    from config import settings
    settings_mode = settings.AUTH_MODE
    settings.AUTH_MODE = "disabled"
    try:
        caplog.set_level(logging.WARNING)
        TestClient(app).post("/investigate", json={"question": "x" * 600 + " jane.doe@acme-corp.com"})
    finally:
        settings.AUTH_MODE = settings_mode
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "Validation error" in joined and "jane.doe" not in joined and "xxxx" not in joined


def test_answer_text_is_redacted_but_evidence_kept():
    from agents.gemini_rca_agent import protect_output
    from models.evidence import EvidenceBundle, EvidenceValidation, IncidentEvidence
    inc = IncidentEvidence(incident_id="INC-001", service="payroll-service", title="Payroll generation failing",
                           root_cause="Database migration missing salary_amount column", status="Resolved")
    clean = {"summary": "Payroll failed for jane.doe@acme-corp.com; missing salary_amount column [INC-001].",
             "recommended_remediation": ["Ask employee ID 44718 to retry"], "confirmed_facts": [],
             "root_cause": {"status": "determined", "statement": "Database migration missing salary_amount column",
                            "refs": ["INC-001"]}}
    out, events = protect_output(clean, EvidenceBundle(question="q", incident_evidence=[inc]),
                                 EvidenceValidation(evidence_strength="MEDIUM"))
    assert "jane.doe" not in out["summary"] and "salary_amount" in out["summary"]
    assert "44718" not in out["recommended_remediation"][0]
    assert out["root_cause"]["statement"] == "Database migration missing salary_amount column"
    assert any("pii" in e for e in events)


def test_audit_events_are_redacted():
    from config import settings
    from pathlib import Path
    from security.audit import audit_event
    audit_event("test", None, note="contact jane.doe@acme-corp.com")
    text = (Path(settings.AUDIT_DIR) / "audit.jsonl").read_text(encoding="utf-8")
    assert "jane.doe" not in text and "<EMAIL_ADDRESS>" in text
