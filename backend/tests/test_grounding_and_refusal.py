"""Regression tests for refusal behaviour and answer grounding (no network)."""

import json

import pytest

from agents import rca_structured as rs
from agents.incident_matcher import MatchResult, parse_match
from models.evidence import (
    DeploymentEvidence,
    EvidenceBundle,
    EvidenceValidation,
    IncidentEvidence,
)

INC1 = IncidentEvidence(incident_id="INC-001", service="payroll-service", severity="Critical",
                        status="Resolved", title="Payroll generation failing",
                        root_cause="Database migration missing salary_amount column",
                        deployment_id="DEP-101", relevance_score=0.83)
INC9 = IncidentEvidence(incident_id="INC-009", service="payroll-service", severity="High",
                        status="Resolved", title="Duplicate payroll records",
                        root_cause="Batch job executed twice", deployment_id="DEP-109",
                        relevance_score=0.73)
DEP1 = DeploymentEvidence(deployment_id="DEP-101", service="payroll-service",
                          time="2026-05-02T10:03:00", change="Database schema migration",
                          incident_id="INC-001", link_status="verified")


def bundle(**kw):
    base = dict(question="Why is payroll generation failing?", incident_evidence=[INC1],
                deployment_evidence=[DEP1])
    base.update(kw)
    return EvidenceBundle(**base)


def answer(**kw):
    base = {
        "answer_status": "answered",
        "summary": "Payroll generation failed because the salary_amount column was missing [INC-001].",
        "confirmed_facts": [{"statement": "INC-001 records a missing salary_amount column.", "refs": ["INC-001"]},
                            {"statement": "DEP-101 ran a database schema migration.", "refs": ["DEP-101"]}],
        "root_cause": {"status": "determined", "statement": "Database migration missing salary_amount column",
                       "refs": ["INC-001"]},
        "conclusions": [], "hypotheses": [], "impact": [], "contributing_factors": [],
        "unknowns": [], "recommended_remediation": [], "preventive_actions": [],
        "confidence": "HIGH", "confidence_reason": "recorded",
    }
    base.update(kw)
    return base


V_MEDIUM = EvidenceValidation(incident_found=True, deployment_found=True, evidence_strength="MEDIUM",
                              missing_evidence=["INC-001: no log lines on payroll-service corroborate this incident"])


class TestGroundingChecks:
    def test_valid_answer_kept_and_confidence_capped(self):
        clean, issues = rs.validate(answer(), bundle(), V_MEDIUM, [])
        assert issues == []
        assert clean["root_cause"]["status"] == "determined"
        assert clean["confidence"] == "MEDIUM"          # model said HIGH, evidence says MEDIUM
        assert "Capped at MEDIUM" in clean["confidence_reason"]
        assert any("no log lines" in u for u in clean["unknowns"])   # missing evidence surfaced

    def test_uncited_claim_removed(self):
        a = answer(conclusions=[{"statement": "Users could not be paid on time.", "refs": []}])
        clean, issues = rs.validate(a, bundle(), V_MEDIUM, [])
        assert clean["conclusions"] == [] and "without a valid evidence citation" in issues[0]

    def test_claim_citing_unknown_record_removed(self):
        a = answer(conclusions=[{"statement": "The auth outage caused this.", "refs": ["INC-002"]}])
        clean, _ = rs.validate(a, bundle(), V_MEDIUM, [])
        assert clean["conclusions"] == []

    def test_claim_naming_fabricated_id_or_date_removed(self):
        a = answer(confirmed_facts=[
            {"statement": "DEP-999 was deployed on 2026-06-01.", "refs": ["DEP-101"]},
            {"statement": "INC-001 records a missing column.", "refs": ["INC-001"]}])
        clean, issues = rs.validate(a, bundle(), V_MEDIUM, [])
        assert [c["statement"] for c in clean["confirmed_facts"]] == ["INC-001 records a missing column."]
        assert "not in the evidence" in issues[0]

    def test_root_cause_must_cite_matched_incident(self):
        a = answer(root_cause={"status": "determined", "statement": "A deployment broke it", "refs": ["DEP-101"]})
        clean, issues = rs.validate(a, bundle(), V_MEDIUM, [])
        assert clean["root_cause"]["status"] == "not_determined"
        assert clean["answer_status"] == "partial"
        assert "did not cite a matched incident" in issues[0]

    def test_summary_with_fabricated_date_replaced(self):
        a = answer(summary="It failed on 2026-09-09 [INC-001].")
        clean, issues = rs.validate(a, bundle(), V_MEDIUM, [])
        assert "2026-09-09" not in clean["summary"] and any("summary" in i for i in issues)

    def test_ids_from_evidence_notes_may_be_named(self):
        v = EvidenceValidation(evidence_strength="LOW",
                               contradictions=["INC-001: deployment link DEP-117 belongs to leave-service"])
        a = answer(confirmed_facts=[{"statement": "The DEP-117 link is quarantined.", "refs": ["INC-001"]}])
        clean, issues = rs.validate(a, bundle(), v, [])
        assert clean["confirmed_facts"] and issues == []

    def test_contradiction_forces_partial(self):
        v = EvidenceValidation(evidence_strength="LOW",
                               contradictions=["INC-017: deployment link DEP-117 belongs to leave-service"])
        clean, _ = rs.validate(answer(), bundle(), v, [])
        assert clean["answer_status"] == "partial" and clean["confidence"] == "LOW"
        assert any("DEP-117" in u for u in clean["unknowns"])

    def test_caveats_moved_from_summary_to_unknowns_not_dropped(self):
        # (Fixture corrected in round 6: it gave INC-001 another incident's root cause,
        # which the claim checks now remove.)
        a = answer(summary="The recorded root cause is a missing salary_amount column [INC-001], but no logs "
                           "corroborate it. However, the deployment link is unverified.")
        clean, _ = rs.validate(a, bundle(), V_MEDIUM, [])
        assert clean["summary"] == "The recorded root cause is a missing salary_amount column [INC-001]."
        assert any("No logs corroborate it" in u for u in clean["unknowns"])
        assert any("deployment link is unverified" in u for u in clean["unknowns"])

    def test_answer_critical_unverifiable_statement_kept(self):
        a = answer(summary="The deployment linked to INC-001 cannot be determined from the records [INC-001].")
        clean, _ = rs.validate(a, bundle(), V_MEDIUM, [])
        assert "cannot be determined" in clean["summary"]

    def test_hypotheses_rendered_separately_and_labelled(self):
        a = answer(hypotheses=[{"statement": "The migration may not have been validated.", "refs": ["DEP-101"]}])
        clean, _ = rs.validate(a, bundle(), V_MEDIUM, [])
        md = rs.render_markdown(clean, bundle())
        assert "## Hypotheses (Not Established)" in md
        assert "may not have been validated" in md.split("## Hypotheses (Not Established)")[1]


class TestEvidencePolicy:
    def test_no_matched_incident_gives_limitation_without_cause(self):
        b = bundle(question="What might lead to incorrect user permissions in the auth-service?",
                   incident_evidence=[], deployment_evidence=[],
                   related_incident_evidence=[INC9])
        clean = rs.policy_answer(b, EvidenceValidation(), "insufficient_evidence")
        assert clean["root_cause"]["status"] == "not_determined"
        assert clean["hypotheses"] == [] and clean["conclusions"] == []
        assert "do not establish the cause" in clean["summary"]
        assert "INC-009" in clean["summary"]            # related records are named, not used
        assert clean["confidence"] == "INSUFFICIENT"

    def test_out_of_scope_answer(self):
        b = bundle(question="What are typical security vulnerabilities in web applications?",
                   incident_evidence=[], deployment_evidence=[])
        clean = rs.policy_answer(b, EvidenceValidation(), "out_of_scope")
        assert clean["answer_status"] == "out_of_scope"
        assert "outside what the copilot supports" in clean["summary"]

    def test_agent_does_not_call_llm_without_matched_incident(self, monkeypatch):
        from agents import gemini_rca_agent

        def boom(*a, **k):
            raise AssertionError("LLM must not be called when no incident matched")

        monkeypatch.setattr(gemini_rca_agent, "generate_text", boom)
        b = bundle(incident_evidence=[], deployment_evidence=[], related_incident_evidence=[INC9])
        result = gemini_rca_agent.generate_gemini_rca(b, EvidenceValidation(), [])
        assert result.answer_source == "policy" and result.answer_status == "insufficient_evidence"
        assert result.root_cause.startswith("Not determined")
        assert result.generation_error is None          # a policy answer is not a failure

    def test_agent_out_of_scope_when_question_general(self, monkeypatch):
        from agents import gemini_rca_agent

        monkeypatch.setattr(gemini_rca_agent, "generate_text", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
        b = bundle(incident_evidence=[], deployment_evidence=[], question_scope="general")
        assert gemini_rca_agent.generate_gemini_rca(b, EvidenceValidation(), []).answer_status == "out_of_scope"

    def test_invalid_json_twice_is_a_failure_not_an_answer(self, monkeypatch):
        from agents import gemini_rca_agent
        from agents.llm_client import LLMResponse

        monkeypatch.setattr(gemini_rca_agent, "generate_text",
                            lambda *a, **k: LLMResponse(text="not json", provider="openai", model="m"))
        result = gemini_rca_agent.generate_gemini_rca(bundle(), V_MEDIUM, [])
        assert result.answer_source == "fallback" and result.generation_error == "error"


class TestMatchParsing:
    def test_normalises_and_defaults_unassessed_to_unrelated(self):
        text = json.dumps({"question_scope": "incident_investigation", "assessments": [
            {"incident_id": "inc-001", "verdict": "same_problem", "reason": "same symptom"},
            {"incident_id": "INC-777", "verdict": "same_problem", "reason": "not a candidate"}]})
        m = parse_match(text, ["INC-001", "INC-009"])
        assert m.matched_ids == ["INC-001"]
        assert {a["incident_id"]: a["verdict"] for a in m.assessments}["INC-009"] == "unrelated"

    def test_related_not_same_is_not_a_match(self):
        text = json.dumps({"assessments": [
            {"incident_id": "INC-002", "verdict": "related_not_same", "reason": "login, not permissions"}]})
        assert parse_match(text, ["INC-002"]).matched_ids == []

    def test_multi_incident_both_matched(self):
        text = json.dumps({"assessments": [
            {"incident_id": "INC-001", "verdict": "same_problem"},
            {"incident_id": "INC-015", "verdict": "same_problem"}]})
        assert parse_match(text, ["INC-015", "INC-001"]).matched_ids == ["INC-015", "INC-001"]

    def test_invalid_json_raises(self):
        with pytest.raises(ValueError):
            parse_match("nope", ["INC-001"])


class TestWorkflowNearMiss:
    """A near-miss question (related incident on the same service, different
    problem) must end as insufficient_evidence with no cause, whatever its
    retrieval score - enforced by application code, not by the prompt."""

    def test_related_but_different_incident_is_not_evidence(self, monkeypatch):
        from workflows import rca_graph

        monkeypatch.setattr(rca_graph, "incident_agent",
                            lambda q, **k: {"incidents": [INC1.model_copy(update={"relevance_score": 0.81})],
                                       "scores": [0.81]})
        monkeypatch.setattr(rca_graph, "match_incidents", lambda q, inc: MatchResult(
            matched_ids=[], assessments=[{"incident_id": "INC-001", "verdict": "related_not_same",
                                          "reason": "different symptom"}]))
        from agents import gemini_rca_agent

        monkeypatch.setattr(gemini_rca_agent, "generate_text",
                            lambda *a, **k: (_ for _ in ()).throw(AssertionError("no LLM call expected")))
        from security.access import system_principal
        state = rca_graph.run_investigation("What may lead to a failure in the payroll reconciliation process?",
                                            principal=system_principal("test"))
        inv = state["investigation"]
        assert inv["answer_status"] == "insufficient_evidence"
        assert inv["evidence_strength"] == "INSUFFICIENT"
        assert inv["root_cause"].startswith("Not determined")
        assert inv["evidence"]["deployment_evidence"] == []      # nothing joined to a non-match
        assert inv["evidence"]["runbook_evidence"] is None
        assert [i["incident_id"] for i in inv["evidence"]["related_incident_evidence"]] == ["INC-001"]

