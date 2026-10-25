"""Tests for LLM error classification/backoff/quota breaker, the shared
relevance filter, and evidence-strength rules. No network calls."""

import json

import httpx
import pytest

from agents.incident_agent import select_relevant
from agents.llm_client import (
    LLMConfigError,
    LLMError,
    LLMQuotaExhaustedError,
    LLMRateLimitError,
    LLMResponse,
    LLMTransientError,
    backoff_delay,
    call_with_retry,
    classify_gemini,
    classify_openai,
    quota_blocked,
    reset_quota_block,
)
from models.evidence import (
    DeploymentEvidence,
    EvidenceBundle,
    IncidentEvidence,
    LogEvidence,
)


@pytest.fixture(autouse=True)
def _clear_quota_breaker():
    reset_quota_block()
    yield
    reset_quota_block()


# --------------------------------------------------------------------------- helpers

def openai_error(cls_name: str, status: int, body: dict, headers: dict | None = None):
    import openai

    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    response = httpx.Response(status, request=request, json=body, headers=headers or {})
    cls = getattr(openai, cls_name)
    return cls(json.dumps(body), response=response, body=body.get("error", body))


def gemini_error(code: int, body: dict):
    from google.genai import errors

    # Same attributes google-genai's APIError.__init__ sets (code, details,
    # status, message); built without __init__ to avoid a real HTTP response.
    cls = errors.ServerError if code >= 500 else errors.ClientError
    exc = cls.__new__(cls)
    exc.code = code
    exc.details = body
    exc.status = body["error"].get("status")
    exc.message = body["error"].get("message")
    exc.response = None
    Exception.__init__(exc, f"{code} {exc.status}. {body}")
    return exc


# --------------------------------------------------------------------------- classification

class TestClassifyOpenAI:
    def test_insufficient_quota_is_quota_exhausted(self):
        exc = openai_error("RateLimitError", 429,
                           {"error": {"code": "insufficient_quota", "type": "insufficient_quota"}})
        assert isinstance(classify_openai(exc), LLMQuotaExhaustedError)

    def test_rate_limit_uses_retry_after(self):
        exc = openai_error("RateLimitError", 429, {"error": {"code": "rate_limit_exceeded"}},
                           headers={"retry-after": "7"})
        err = classify_openai(exc)
        assert isinstance(err, LLMRateLimitError) and err.retry_after == 7.0

    @pytest.mark.parametrize("cls_name,status", [
        ("AuthenticationError", 401), ("NotFoundError", 404), ("BadRequestError", 400)])
    def test_config_errors_not_retryable(self, cls_name, status):
        err = classify_openai(openai_error(cls_name, status, {"error": {"message": "x"}}))
        assert isinstance(err, LLMConfigError) and not err.retryable

    def test_server_error_is_transient(self):
        err = classify_openai(openai_error("InternalServerError", 503, {"error": {"message": "x"}}))
        assert isinstance(err, LLMTransientError) and err.retryable


class TestClassifyGemini:
    def test_daily_quota_is_quota_exhausted(self):
        body = {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": "quota",
                          "details": [{"@type": "type.googleapis.com/google.rpc.QuotaFailure",
                                       "violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]},
                                      {"@type": "type.googleapis.com/google.rpc.RetryInfo",
                                       "retryDelay": "82002s"}]}}
        err = classify_gemini(gemini_error(429, body))
        assert isinstance(err, LLMQuotaExhaustedError)

    def test_per_minute_limit_is_rate_limit(self):
        body = {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": "slow down",
                          "details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo",
                                       "retryDelay": "12s"}]}}
        err = classify_gemini(gemini_error(429, body))
        assert isinstance(err, LLMRateLimitError) and err.retry_after == 12.0

    def test_free_tier_per_minute_limit_with_billing_text_is_rate_limit(self):
        # Realistic free-tier per-minute 429: mentions plan/billing and the
        # free_tier metric, but the quotaId is per-minute -> retryable.
        body = {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED",
                          "message": ("You exceeded your current quota, please check your plan and "
                                      "billing details. Quota exceeded for metric: generativelanguage."
                                      "googleapis.com/generate_content_free_tier_requests"),
                          "details": [{"@type": "type.googleapis.com/google.rpc.QuotaFailure",
                                       "violations": [{"quotaId": "GenerateRequestsPerMinutePerProjectPerModel-FreeTier"}]},
                                      {"@type": "type.googleapis.com/google.rpc.RetryInfo",
                                       "retryDelay": "21s"}]}}
        err = classify_gemini(gemini_error(429, body))
        assert isinstance(err, LLMRateLimitError) and err.retry_after == 21.0

    @pytest.mark.parametrize("exc", [
        "requests_timeout", "requests_connection", "builtin_timeout"])
    def test_network_errors_are_transient(self, exc):
        import requests

        e = {"requests_timeout": requests.exceptions.ReadTimeout("read timed out"),
             "requests_connection": requests.exceptions.ConnectionError("conn reset"),
             "builtin_timeout": TimeoutError("timed out")}[exc]
        assert isinstance(classify_gemini(e), LLMTransientError)

    def test_503_is_transient(self):
        body = {"error": {"code": 503, "status": "UNAVAILABLE", "message": "high demand"}}
        assert isinstance(classify_gemini(gemini_error(503, body)), LLMTransientError)

    def test_404_model_is_config(self):
        body = {"error": {"code": 404, "status": "NOT_FOUND", "message": "model not available"}}
        assert isinstance(classify_gemini(gemini_error(404, body)), LLMConfigError)


# --------------------------------------------------------------------------- retry loop

def _ok():
    return LLMResponse(text="ok", provider="gemini", model="m")


class TestRetry:
    def test_backoff_bounds_and_retry_after(self):
        for attempt in range(1, 8):
            d = backoff_delay(attempt, base=1.0, cap=30.0)
            assert 0.0 <= d <= min(30.0, 2 ** (attempt - 1))
        assert backoff_delay(1, 1.0, 30.0, retry_after=12.0) >= 12.0

    def test_transient_errors_retried_with_backoff_then_succeed(self):
        body = {"error": {"code": 503, "status": "UNAVAILABLE", "message": "busy"}}
        calls, sleeps = [], []

        def call():
            calls.append(1)
            if len(calls) < 3:
                raise gemini_error(503, body)
            return _ok()

        resp = call_with_retry(call, provider="gemini", max_retries=2, base=1.0, cap=30.0,
                               quota_cooldown=60, sleep=sleeps.append)
        assert resp.text == "ok" and resp.attempts == 3
        assert len(sleeps) == 2  # two backoffs, no immediate hammering

    def test_quota_exhausted_not_retried_and_blocks_later_calls(self):
        body = {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED",
                          "message": "free_tier_requests exceeded",
                          "details": [{"@type": "type.googleapis.com/google.rpc.QuotaFailure",
                                       "violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]}]}}
        calls, sleeps = [], []

        def call():
            calls.append(1)
            raise gemini_error(429, body)

        with pytest.raises(LLMQuotaExhaustedError):
            call_with_retry(call, provider="gemini", max_retries=3, base=1.0, cap=30.0,
                            quota_cooldown=60, sleep=sleeps.append)
        assert len(calls) == 1 and sleeps == []
        assert quota_blocked("gemini")
        with pytest.raises(LLMQuotaExhaustedError):
            call_with_retry(call, provider="gemini", max_retries=3, base=1.0, cap=30.0,
                            quota_cooldown=60, sleep=sleeps.append)
        assert len(calls) == 1  # breaker: no further provider calls

    def test_config_error_fails_immediately(self):
        calls = []

        def call():
            calls.append(1)
            raise openai_error("NotFoundError", 404, {"error": {"message": "no such model"}})

        with pytest.raises(LLMConfigError):
            call_with_retry(call, provider="openai", max_retries=3, base=1.0, cap=30.0,
                            quota_cooldown=60, sleep=lambda s: None)
        assert len(calls) == 1

    def test_unknown_error_not_retried(self):
        calls = []

        def call():
            calls.append(1)
            raise RuntimeError("boom")

        with pytest.raises(LLMError):
            call_with_retry(call, provider="openai", max_retries=3, base=1.0, cap=30.0,
                            quota_cooldown=60, sleep=lambda s: None)
        assert len(calls) == 1


class TestGenerateTextConfig:
    def test_missing_key_fails_clearly(self, monkeypatch):
        import config
        from agents.gemini_rca_agent import generate_text

        monkeypatch.setattr(config.settings, "LLM_PROVIDER", "openai")
        monkeypatch.setattr(config.settings, "OPENAI_API_KEY", None)
        with pytest.raises(LLMConfigError, match="OPENAI_API_KEY"):
            generate_text("prompt")

    def test_unknown_provider_fails_clearly(self, monkeypatch):
        import config
        from agents.gemini_rca_agent import generate_text

        monkeypatch.setattr(config.settings, "LLM_PROVIDER", "nope")
        with pytest.raises(LLMConfigError):
            generate_text("prompt")


# --------------------------------------------------------------------------- relevance filter

class TestSelectRelevant:
    def test_floor_and_margin(self):
        scored = [("A", 0.83), ("B", 0.76), ("C", 0.70), ("D", 0.58)]
        assert select_relevant(scored, min_score=0.60, margin=0.10) == ["A", "B"]

    def test_everything_below_floor_is_dropped(self):
        assert select_relevant([("A", 0.55), ("B", 0.50)], min_score=0.60, margin=0.10) == []

    def test_close_multi_incident_scores_kept(self):
        scored = [("A", 0.80), ("B", 0.79), ("C", 0.65)]
        assert select_relevant(scored, min_score=0.60, margin=0.10) == ["A", "B"]


# --------------------------------------------------------------------------- evidence strength

def _bundle(score: float, deployment_id="DEP-101", log_incident="INC-001",
            incident_id="INC-001", incident_deployment="DEP-101"):
    """INC-001 (payroll) with optional linked deployment and attributed log line.
    deployment_link_status() is checked against the real deployments.json."""
    return EvidenceBundle(
        question="Why is payroll failing?",
        incident_evidence=[IncidentEvidence(incident_id=incident_id, service="payroll-service",
                                            deployment_id=incident_deployment, relevance_score=score)],
        deployment_evidence=[DeploymentEvidence(deployment_id=deployment_id, service="payroll-service",
                                                incident_id=incident_id)] if deployment_id else [],
        log_evidence=[LogEvidence(timestamp="2026-05-02 10:30:00", service="payroll-service",
                                  level="ERROR", message="column salary_amount missing",
                                  incident_id=log_incident)] if log_incident else [],
    )


def _validation(bundle):
    from models.evidence import RetrievalMetadata
    from workflows.rca_graph import evidence_validation_node

    bundle.retrieval_metadata = RetrievalMetadata(
        incident_count=len(bundle.incident_evidence),
        deployment_count=len(bundle.deployment_evidence),
        log_count=len(bundle.log_evidence))
    return evidence_validation_node({"bundle": bundle})["validation"]


def _strength(bundle):
    return _validation(bundle).evidence_strength


class TestEvidenceStrength:
    def test_strong_evidence_is_high(self):
        assert _strength(_bundle(0.83)) == "HIGH"

    def test_relevance_alone_is_never_high(self):
        # strong retrieval score but no deployment and no logs -> LOW
        assert _strength(_bundle(0.95, deployment_id=None, log_incident=None)) == "LOW"

    def test_weak_match_with_full_corroboration_is_medium(self):
        assert _strength(_bundle(0.66)) == "MEDIUM"

    def test_missing_logs_is_medium_and_reported(self):
        v = _validation(_bundle(0.83, log_incident=None))
        assert v.evidence_strength == "MEDIUM"
        assert any("no log lines" in m for m in v.missing_evidence)

    def test_unrelated_logs_do_not_count(self):
        # a log line attributed to a different incident is not corroboration
        assert _strength(_bundle(0.83, deployment_id=None, log_incident="INC-999")) == "LOW"

    def test_contradictory_deployment_link_is_low(self):
        # INC-017 references DEP-117, which deployments.json puts on leave-service
        v = _validation(_bundle(0.9, deployment_id=None, incident_id="INC-017",
                                incident_deployment="DEP-117", log_incident="INC-017"))
        assert v.evidence_strength == "LOW"
        assert v.contradictions and "DEP-117" in v.contradictions[0]

    def test_no_matched_incident_is_insufficient(self):
        b = _bundle(0.83)
        b.incident_evidence = []
        assert _strength(b) == "INSUFFICIENT"

    def test_multi_incident_takes_weakest(self):
        b = _bundle(0.83)
        b.incident_evidence.append(IncidentEvidence(incident_id="INC-015", service="payroll-service",
                                                    deployment_id="DEP-115", relevance_score=0.8))
        assert _strength(b) == "LOW"   # INC-015 has no deployment/log evidence here

    def test_match_check_unavailable_caps_at_low(self):
        b = _bundle(0.83)
        b.match_available = False
        assert _strength(b) == "LOW"


class TestProviderTimeouts:
    def test_gemini_timeout_is_seconds(self, monkeypatch):
        import config
        from agents.gemini_rca_agent import gemini_http_options

        monkeypatch.setattr(config.settings, "GEMINI_TIMEOUT_MS", 60000)
        assert gemini_http_options()["timeout"] == 60.0   # google-genai 0.6 expects seconds

    def test_openai_timeout_is_seconds_and_sdk_retries_disabled(self, monkeypatch):
        import config
        from agents import gemini_rca_agent

        monkeypatch.setattr(config.settings, "OPENAI_API_KEY", "test-key")
        monkeypatch.setattr(config.settings, "OPENAI_TIMEOUT_MS", 30000)
        monkeypatch.setattr(gemini_rca_agent, "_openai_client", None)
        c = gemini_rca_agent._openai()
        assert c.timeout == 30.0 and c.max_retries == 0
        monkeypatch.setattr(gemini_rca_agent, "_openai_client", None)
