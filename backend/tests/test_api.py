"""API tests. The LangGraph workflow and Qdrant are mocked so no Gemini
API credits are consumed and no external services are needed."""

import pytest
from fastapi.testclient import TestClient

from app import app
from utils.rate_limit import investigate_limiter


client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    investigate_limiter._hits.clear()
    yield
    investigate_limiter._hits.clear()


@pytest.fixture()
def mock_graph(monkeypatch):
    """Replace the compiled LangGraph app with a stub returning a full
    structured investigation state (as the real workflow produces)."""
    from api import routes

    def fake_invoke(state):
        investigation = {
            "question": state["question"],
            "status": "success",
            "summary": "Test summary.",
            "impact": "Payroll service affected.",
            "root_cause": "Bad migration.",
            "confidence": "HIGH",
            "evidence_strength": "HIGH",
            "contributing_factors": ["Weak monitoring"],
            "recommended_remediation": ["Rollback deployment"],
            "preventive_actions": ["Add migration checks"],
            "observed_evidence": ["INC-001 exists"],
            "investigation_details": "Used INC-001.",
            "timeline": [
                {
                    "timestamp": "2026-05-02T10:03:00",
                    "event": "Deployment DEP-101 executed",
                    "source": "deployments.json",
                }
            ],
            "evidence": {
                "question": state["question"],
                "incident_evidence": [{
                    "incident_id": "INC-001",
                    "deployment_id": "DEP-101",
                    "service": "payroll-service",
                    "severity": "Critical",
                    "status": "Resolved",
                    "title": "Payroll generation failing",
                    "root_cause": "Database migration missing salary_amount column",
                    "relevance_score": 0.62,
                }],
                "deployment_evidence": [{
                    "deployment_id": "DEP-101",
                    "service": "payroll-service",
                    "time": "2026-05-02T10:03:00",
                    "change": "Database schema migration",
                }],
                "log_evidence": [{
                    "timestamp": "2026-05-02 10:05:12",
                    "level": "ERROR",
                    "service": "payroll-service",
                    "message": "migration failed",
                    "source": "logs.txt",
                }],
                "runbook_evidence": {
                    "name": "payment_failure",
                    "title": "Payroll Failure Runbook",
                    "content": "Checks...",
                },
                "retrieval_metadata": {
                    "incident_count": 1,
                    "deployment_count": 1,
                    "log_count": 1,
                    "runbook_count": 1,
                    "min_relevance_score": 0.62,
                    "retrieval_errors": [],
                },
                "investigation_timestamp": "2026-05-02T10:10:00+00:00",
            },
            "validation": {
                "incident_found": True,
                "deployment_found": True,
                "logs_found": True,
                "runbook_found": True,
                "evidence_strength": "HIGH",
                "notes": [],
            },
            "report_markdown": "# Root Cause Analysis\n\n## Summary\nTest.\n\n## Confidence\nHigh - clear.\n",
            "message": None,
        }
        return {"question": state["question"], "investigation": investigation}

    monkeypatch.setattr(routes.rca_graph, "invoke", fake_invoke)
    return fake_invoke


class TestHealth:
    def test_health_returns_structured_status(self):
        response = client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "healthy"
        assert isinstance(body["qdrant"], bool)
        assert isinstance(body["gemini_configured"], bool)


class TestInvestigateValidation:
    def test_missing_question_is_rejected(self):
        response = client.post("/investigate", json={})
        assert response.status_code == 422
        assert response.json()["status"] == "error"

    def test_too_short_question_is_rejected(self):
        response = client.post("/investigate", json={"question": "hi"})
        assert response.status_code == 422

    def test_blank_question_is_rejected(self):
        response = client.post("/investigate", json={"question": "        "})
        assert response.status_code == 422

    def test_overlong_question_is_rejected(self):
        response = client.post(
            "/investigate", json={"question": "a" * 501}
        )
        assert response.status_code == 422


class TestInvestigate:
    def test_successful_investigation_returns_structured_payload(self, mock_graph):
        response = client.post(
            "/investigate", json={"question": "Why is payroll failing?"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "success"

        investigation = body["investigation"]
        assert investigation["summary"] == "Test summary."
        assert investigation["root_cause"] == "Bad migration."
        assert investigation["confidence"] == "HIGH"
        assert investigation["evidence_strength"] == "HIGH"
        assert investigation["recommended_remediation"] == ["Rollback deployment"]
        assert investigation["timeline"][0]["source"] == "deployments.json"
        # markdown fallback still present
        assert "Root Cause Analysis" in body["report"]

        evidence = investigation["evidence"]
        assert evidence["incident_evidence"][0]["incident_id"] == "INC-001"
        assert evidence["incident_evidence"][0]["relevance_score"] == 0.62
        assert evidence["deployment_evidence"][0]["deployment_id"] == "DEP-101"
        assert evidence["log_evidence"][0]["level"] == "ERROR"
        assert evidence["runbook_evidence"]["name"] == "payment_failure"

    def test_validation_block_present(self, mock_graph):
        response = client.post(
            "/investigate", json={"question": "Why is payroll failing?"}
        )
        validation = response.json()["investigation"]["validation"]
        assert validation == {
            "incident_found": True,
            "deployment_found": True,
            "logs_found": True,
            "runbook_found": True,
            "evidence_strength": "HIGH",
            "notes": [],
        }

    def test_no_raw_exception_on_workflow_failure(self, monkeypatch):
        from api import routes

        def broken_invoke(state):
            raise RuntimeError("internal database path leaked")

        monkeypatch.setattr(routes.rca_graph, "invoke", broken_invoke)
        response = client.post(
            "/investigate", json={"question": "Why is payroll failing?"}
        )
        assert response.status_code == 500
        body = response.json()
        assert body["status"] == "error"
        assert "internal database path" not in body["message"]

    def test_rate_limiting(self, mock_graph, monkeypatch):
        import config

        monkeypatch.setattr(config.settings, "INVESTIGATE_RATE_LIMIT", 2)
        from utils.rate_limit import RateLimiter

        test_limiter = RateLimiter(2, 60)
        monkeypatch.setattr(
            "api.routes.investigate_limiter", test_limiter
        )
        for _ in range(2):
            response = client.post(
                "/investigate", json={"question": "Why is payroll failing?"}
            )
            assert response.status_code == 200
        response = client.post(
            "/investigate", json={"question": "Why is payroll failing?"}
        )
        assert response.status_code == 429


class TestSearch:
    def test_search_validation(self):
        response = client.post("/search", json={"query": ""})
        assert response.status_code == 422

    def test_search_invalid_limit(self):
        response = client.post(
            "/search", json={"query": "payroll", "limit": 999}
        )
        assert response.status_code == 422
