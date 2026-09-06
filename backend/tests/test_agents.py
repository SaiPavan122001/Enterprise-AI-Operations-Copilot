"""Unit tests for the RCA agents and the evidence layer.

External services (Gemini, Qdrant) are mocked - no API credits consumed.
"""

import pytest

from agents.deployment_agent import investigate_deployments
from agents.gemini_rca_agent import (
    _extract_confidence,
    generate_gemini_rca,
    _final_confidence,
)
from agents.log_agent import investigate_logs
from agents.runbook_agent import retrieve_runbook
from models.evidence import (
    DeploymentEvidence,
    EvidenceBundle,
    EvidenceValidation,
    IncidentEvidence,
    LogEvidence,
    RetrievalMetadata,
    RunbookEvidence,
    TimelineEvent,
)
from workflows.rca_graph import _build_timeline


INCIDENT = IncidentEvidence(
    incident_id="INC-001",
    deployment_id="DEP-101",
    service="payroll-service",
    severity="Critical",
    status="Resolved",
    title="Payroll generation failing",
    root_cause="Database migration missing salary_amount column",
    relevance_score=0.62,
)

DEPLOYMENT = DeploymentEvidence(
    deployment_id="DEP-101",
    service="payroll-service",
    time="2026-05-02T10:03:00",
    change="Database schema migration",
)

DEPLOYMENTS_RAW = [
    {"deployment_id": "DEP-101", "service": "payroll-service", "time": "2026-05-02T10:03:00", "change": "Database schema migration"},
    {"deployment_id": "DEP-102", "service": "auth-service", "time": "2026-05-03T10:06:00", "change": "JWT authentication upgrade"},
]


def make_bundle(**overrides):
    defaults = dict(
        question="Why is payroll failing?",
        incident_evidence=[INCIDENT],
        deployment_evidence=[DEPLOYMENT],
        log_evidence=[
            LogEvidence(
                timestamp="2026-05-02 10:05:12",
                level="ERROR",
                service="payroll-service",
                message="Database migration failed: column salary_amount not found",
            )
        ],
        runbook_evidence=RunbookEvidence(
            name="payment_failure",
            title="Payroll Failure Runbook",
            content="Checks:\n1. Verify schema migration\n2. Validate salary_amount column",
        ),
        retrieval_metadata=RetrievalMetadata(
            incident_count=1,
            deployment_count=1,
            log_count=1,
            runbook_count=1,
            min_relevance_score=0.62,
        ),
    )
    defaults.update(overrides)
    return EvidenceBundle(**defaults)


VALIDATION = EvidenceValidation(
    incident_found=True,
    deployment_found=True,
    logs_found=True,
    runbook_found=True,
    evidence_strength="HIGH",
)

TIMELINE = [
    TimelineEvent(
        timestamp="2026-05-02T10:03:00",
        event="Deployment DEP-101 executed on payroll-service",
        source="deployments.json",
    )
]

class TestDeploymentCorrelation:
    def test_correlates_by_deployment_id(self, monkeypatch):
        monkeypatch.setattr(
            "agents.deployment_agent.get_deployments", lambda: DEPLOYMENTS_RAW
        )
        result = investigate_deployments([INCIDENT])
        assert len(result) == 1
        assert result[0].deployment_id == "DEP-101"
        assert result[0].change == "Database schema migration"

    def test_service_fallback_only_without_deployment_id(self, monkeypatch):
        monkeypatch.setattr(
            "agents.deployment_agent.get_deployments", lambda: DEPLOYMENTS_RAW
        )
        incident = INCIDENT.model_copy(update={"deployment_id": None})
        result = investigate_deployments([incident])
        assert len(result) == 1
        assert result[0].service == "payroll-service"

    def test_no_incidents_returns_empty(self):
        assert investigate_deployments([]) == []


class TestLogRetrieval:
    def test_parses_structured_log_lines(self, monkeypatch):
        monkeypatch.setattr(
            "agents.log_agent.get_logs",
            lambda: [
                "2026-05-02 10:05:12 payroll-service ERROR migration failed",
                "2026-05-02 10:05:13 payroll-service INFO ok",
            ],
        )
        result = investigate_logs([INCIDENT])
        assert len(result) == 2
        error_entry = next(e for e in result if e.level == "ERROR")
        assert error_entry.service == "payroll-service"
        assert error_entry.timestamp == "2026-05-02 10:05:12"
        assert error_entry.source == "logs.txt"

    def test_prioritises_errors_over_info(self, monkeypatch):
        monkeypatch.setattr(
            "agents.log_agent.get_logs",
            lambda: [
                "2026-05-02 10:00:01 payroll-service INFO ok",
                "2026-05-02 10:00:02 payroll-service ERROR migration failed",
            ],
        )
        result = investigate_logs([INCIDENT])
        assert result[0].level == "ERROR"

    def test_falls_back_to_keywords(self, monkeypatch):
        monkeypatch.setattr(
            "agents.log_agent.get_logs",
            lambda: ["2026-05-02 10:00:00 gateway-service ERROR 502 upstream failed"],
        )
        result = investigate_logs([], keywords=["502"])
        assert len(result) == 1


class TestRunbookRetrieval:
    def test_payroll_question_matches_payment_runbook(self):
        result = retrieve_runbook("Why is payroll failing?", [INCIDENT])
        assert result is not None
        assert result.name == "payment_failure"
        assert "salary_amount" in result.content

    def test_jwt_question_matches_auth_runbook(self):
        result = retrieve_runbook("Investigate JWT login failures", [])
        assert result is not None
        assert result.name == "jwt_auth_failure"

    def test_unrelated_question_returns_none(self):
        assert retrieve_runbook("What is the weather today?", []) is None


class TestTimeline:
    def test_timeline_uses_only_real_timestamps(self):
        timeline = _build_timeline(make_bundle())
        assert timeline
        assert all(e.source in ("deployments.json", "logs.txt") for e in timeline)
        times = [e.timestamp for e in timeline]
        assert times == sorted(times)  # chronological

    def test_empty_timeline_when_no_timestamps(self):
        bundle = make_bundle(
            deployment_evidence=[],
            log_evidence=[LogEvidence(message="line without timestamp")],
        )
        assert _build_timeline(bundle) == []

class TestEvidenceValidationConfidence:
    def test_evidence_layer_is_authoritative(self):
        assert _final_confidence("HIGH", VALIDATION) == "HIGH"
        assert (
            _final_confidence("HIGH", EvidenceValidation(evidence_strength="LOW"))
            == "LOW"
        )
        assert (
            _final_confidence(
                "MEDIUM", EvidenceValidation(evidence_strength="INSUFFICIENT")
            )
            == "INSUFFICIENT"
        )

    def test_extract_confidence(self):
        assert _extract_confidence("## Confidence\nHigh - clear evidence.") == "HIGH"


class TestGeminiFailure:
    def test_falls_back_to_evidence_only_result(self, monkeypatch):
        from agents import gemini_rca_agent
        import config

        monkeypatch.setattr(config.settings, "GEMINI_MAX_RETRIES", 0)

        class FailingModels:
            def generate_content(self, **kwargs):
                raise RuntimeError("boom")

        monkeypatch.setattr(
            gemini_rca_agent, "client", type("C", (), {"models": FailingModels()})()
        )

        result = generate_gemini_rca(make_bundle(), VALIDATION, TIMELINE)
        assert result.status == "error"
        assert result.confidence in ("LOW", "INSUFFICIENT")
        assert result.root_cause is None  # no invented root cause
        assert "boom" not in (result.report_markdown or "")
        assert any("salary_amount" in item for item in result.recommended_remediation)
        assert any("INC-001" in item for item in result.observed_evidence)

    def test_success_produces_structured_result(self, monkeypatch):
        from agents import gemini_rca_agent

        markdown = (
            "# Root Cause Analysis\n\n## Summary\nTest summary.\n\n## Impact\nImpact.\n\n"
            "## Evidence\n- INC-001 exists\n\n## Root Cause\nBad migration.\n\n"
            "## Contributing Factors\n- Weak monitoring\n\n"
            "## Recommended Remediation\n1. Rollback deployment\n2. Re-run migration\n\n"
            "## Preventive Actions\n1. Add checks\n\n## Confidence\nHigh - clear.\n\n"
            "## Investigation Details\nUsed INC-001.\n"
        )

        class FakeResponse:
            text = markdown

        class FakeModels:
            def generate_content(self, **kwargs):
                return FakeResponse()

        monkeypatch.setattr(
            gemini_rca_agent, "client", type("C", (), {"models": FakeModels()})()
        )

        result = generate_gemini_rca(make_bundle(), VALIDATION, TIMELINE)
        assert result.status == "success"
        assert result.summary == "Test summary."
        assert result.root_cause == "Bad migration."
        assert result.recommended_remediation == [
            "Rollback deployment",
            "Re-run migration",
        ]
        assert result.preventive_actions == ["Add checks"]
        assert result.contributing_factors == ["Weak monitoring"]
        assert result.confidence == "HIGH"
        assert result.timeline == TIMELINE
        assert result.evidence.incident_evidence[0].incident_id == "INC-001"
        assert result.validation.evidence_strength == "HIGH"
