"""Regression tests for the two-stage evidence matcher (requirement decomposition,
per-requirement service rules, metadata constraints, generic requirements,
fail-soft). The LLM is faked per call purpose; no network."""

import json
from types import SimpleNamespace

import pytest

from agents import gemini_rca_agent
from agents.incident_matcher import (
    MatchResult,
    apply_deterministic_checks,
    is_generic,
    match_incidents,
    named_severities,
    normalize_requirement,
)
from models.evidence import IncidentEvidence

SERVICES = {"payroll-service", "auth-service", "leave-service", "notification-service",
            "gateway-service", "employee-service", "reporting-service"}


def inc(iid, service, title, root="r", severity="High"):
    return IncidentEvidence(incident_id=iid, service=service, title=title, root_cause=root,
                            severity=severity, relevance_score=0.8)


PAYROLL = [inc("INC-001", "payroll-service", "Payroll generation failing",
               "Database migration missing salary_amount column", "Critical"),
           inc("INC-009", "payroll-service", "Duplicate payroll records", "Batch job executed twice"),
           inc("INC-015", "payroll-service", "Payroll API returning 500 errors", "Schema version mismatch",
               "Critical")]
AUTH_LEAVE = [inc("INC-002", "auth-service", "Users unable to login", "JWT signing key mismatch"),
              inc("INC-008", "auth-service", "SSO authentication failure", "OAuth certificate expired", "Critical"),
              inc("INC-003", "leave-service", "Leave balances incorrect", "Cache invalidation failure")]


def fake_llm(monkeypatch, stage_a: dict, requirements=None, symptom=None, cause=None, fail=()):
    """stage_a: {iid: verdict} for the whole question; requirements: decomposer output;
    symptom / cause: {requirement problem: [matched ids]}."""
    calls = []

    def gen(prompt, json_mode=False, purpose="rca", temperature=None):
        calls.append(purpose)
        if purpose in fail:
            raise RuntimeError("provider down")
        if purpose == "incident_match":
            body = {"question_scope": "incident_investigation",
                    "assessments": [{"incident_id": k, "verdict": v, "reason": "x"} for k, v in stage_a.items()]}
        elif purpose == "incident_match_decompose":
            body = {"requirements": requirements or []}
        elif purpose == "incident_match_requirement":
            hits = next((ids for p, ids in (symptom or {}).items() if f"QUESTION:\n{p}" in prompt), [])
            body = {"assessments": [{"incident_id": i, "verdict": "same_problem"} for i in hits]}
        elif purpose == "incident_match_cause":
            body = {"matches": next((ids for p, ids in (cause or {}).items() if p in prompt), [])}
        else:
            raise AssertionError(purpose)
        return SimpleNamespace(text=json.dumps(body))

    monkeypatch.setattr(gemini_rca_agent, "generate_text", gen)
    return calls


def run(question, cands):
    return apply_deterministic_checks(question, match_incidents(question, cands), cands, SERVICES, set())


class TestStageAUnchanged:
    def test_single_requirement_question_uses_stage_a_only(self, monkeypatch):
        calls = fake_llm(monkeypatch, {"INC-001": "same_problem", "INC-009": "related_not_same"},
                         requirements=[{"kind": "symptom", "problem": "payroll generation failing"}])
        r = run("Why is payroll generation failing?", PAYROLL[:2])
        assert r.matched_ids == ["INC-001"]
        assert r.requirements == []          # one requirement -> Stage B not used
        assert "incident_match_requirement" not in calls

    def test_out_of_scope_rejected_by_stage_a_stays_rejected(self, monkeypatch):
        fake_llm(monkeypatch, {"INC-001": "related_not_same", "INC-015": "related_not_same"},
                 requirements=[{"kind": "symptom", "problem": "payroll reconciliation failure"}])
        assert run("What may lead to a failure in payroll reconciliation?", PAYROLL).matched_ids == []


class TestMultiIncidentRecall:
    def test_incident_described_by_its_cause_is_recovered(self, monkeypatch):
        # D3 shape: Stage A finds only the symptom-described incident.
        fake_llm(monkeypatch, {"INC-001": "same_problem", "INC-009": "related_not_same", "INC-015": "related_not_same"},
                 requirements=[{"kind": "cause", "problem": "database structure", "service": "payroll-service"},
                               {"kind": "cause", "problem": "batch job execution", "service": "payroll-service"}],
                 cause={"database structure": ["INC-001", "INC-015"], "batch job execution": ["INC-009"]})
        r = run("Issues in the payroll-service incidents involving the database structure and batch job execution?",
                PAYROLL)
        # INC-015 is NOT added: the "database structure" requirement is already covered by Stage A.
        assert r.matched_ids == ["INC-001", "INC-009"]

    def test_incidents_requested_by_service_cross_service(self, monkeypatch):
        # D4 shape: no symptom named; the decomposer mislabels "root causes" as a cause.
        fake_llm(monkeypatch, {i.incident_id: "related_not_same" for i in AUTH_LEAVE},
                 requirements=[{"kind": "cause", "problem": "root causes of the incidents", "service": "auth-service"},
                               {"kind": "cause", "problem": "root causes of the incidents", "service": "leave-service"}])
        r = run("What were the root causes of the incidents in the auth-service and leave-service?", AUTH_LEAVE)
        assert set(r.matched_ids) == {"INC-002", "INC-008", "INC-003"}
        assert {q["kind"] for q in r.requirements} == {"service"}

    def test_two_symptoms_each_judged_independently(self, monkeypatch):
        fake_llm(monkeypatch, {"INC-002": "same_problem", "INC-003": "related_not_same", "INC-008": "related_not_same"},
                 requirements=[{"kind": "symptom", "problem": "users unable to login"},
                               {"kind": "symptom", "problem": "leave balances incorrect"}],
                 symptom={"users unable to login": ["INC-002"], "leave balances incorrect": ["INC-003"]})
        r = run("How did the login failures affect the incorrect time-off balances?", AUTH_LEAVE)
        assert r.matched_ids == ["INC-002", "INC-003"]


class TestHardConstraints:
    def test_service_requirement_needs_a_service_the_question_names(self, monkeypatch):
        # The decomposer invents a service the user never named: it cannot add evidence.
        fake_llm(monkeypatch, {i.incident_id: "related_not_same" for i in AUTH_LEAVE},
                 requirements=[{"kind": "service", "problem": "incidents", "service": "auth-service"},
                               {"kind": "service", "problem": "incidents", "service": "leave-service"}])
        assert run("What went wrong with sign-in and time-off recently?", AUTH_LEAVE).matched_ids == []

    def test_requirement_service_mismatch_downgraded(self, monkeypatch):
        fake_llm(monkeypatch, {i.incident_id: "related_not_same" for i in AUTH_LEAVE},
                 requirements=[{"kind": "symptom", "problem": "login failing", "service": "auth-service"},
                               {"kind": "symptom", "problem": "balances wrong", "service": "leave-service"}],
                 symptom={"login failing on auth-service": ["INC-002", "INC-003"],
                          "balances wrong on leave-service": []})
        r = run("Compare the auth-service login failure with the leave-service balances problem", AUTH_LEAVE)
        assert r.matched_ids == ["INC-002"]     # INC-003 is on leave-service, not R1's auth-service

    @pytest.mark.parametrize("question,expected", [
        ("the two critical incidents in payroll", {"critical"}),
        ("high-severity incidents on auth", {"high"}),
        ("incidents with severity of medium", {"medium"}),
        ("why is there a high API error rate?", set()),          # symptom, not a severity
        ("payroll generation failing", set()),
    ])
    def test_named_severities(self, question, expected):
        assert named_severities(question) == expected

    def test_severity_is_a_hard_constraint(self):
        r = apply_deterministic_checks(
            "What are the root causes of the two critical payroll-service incidents?",
            MatchResult(matched_ids=["INC-001", "INC-009", "INC-015"],
                        assessments=[{"incident_id": i.incident_id, "verdict": "same_problem", "reason": "llm"}
                                     for i in PAYROLL]),
            PAYROLL, SERVICES, set())
        assert r.matched_ids == ["INC-001", "INC-015"]

    def test_named_id_overrides_severity_and_service(self):
        r = apply_deterministic_checks(
            "Was INC-009 a critical leave-service incident?",
            MatchResult(assessments=[{"incident_id": "INC-009", "verdict": "unrelated", "reason": "llm"}]),
            PAYROLL[1:2], SERVICES, set())
        assert r.matched_ids == ["INC-009"]


class TestGenericRequirements:
    @pytest.mark.parametrize("text,service,generic", [
        ("root causes of the incidents that occurred", "auth-service", True),
        ("issues in auth-service", "auth-service", True),
        ("the incidents", None, True),
        ("batch job execution", None, False),
        ("login failures", "auth-service", False),
    ])
    def test_is_generic(self, text, service, generic):
        assert is_generic(text, service) is generic

    def test_generic_requirement_without_service_is_dropped(self):
        assert normalize_requirement({"id": "R1", "kind": "symptom", "problem": "the issues",
                                      "service": None}) is None

    def test_generic_requirement_with_service_becomes_service_kind(self):
        r = normalize_requirement({"id": "R1", "kind": "cause", "problem": "root causes",
                                   "service": "auth-service"})
        assert r["kind"] == "service"


class TestFailSoft:
    def test_decomposition_failure_keeps_stage_a(self, monkeypatch):
        fake_llm(monkeypatch, {"INC-001": "same_problem", "INC-009": "related_not_same"},
                 fail=("incident_match_decompose",))
        r = match_incidents("payroll failing and duplicate records", PAYROLL[:2])
        assert r.available and r.matched_ids == ["INC-001"]

    def test_requirement_failure_never_adds_evidence(self, monkeypatch):
        fake_llm(monkeypatch, {"INC-001": "related_not_same", "INC-009": "related_not_same"},
                 requirements=[{"kind": "symptom", "problem": "a"}, {"kind": "symptom", "problem": "b"}],
                 fail=("incident_match_requirement",))
        r = match_incidents("a and b?", PAYROLL[:2])
        assert r.available and r.matched_ids == []

    def test_stage_a_failure_is_unavailable(self, monkeypatch):
        fake_llm(monkeypatch, {}, fail=("incident_match",))
        assert not match_incidents("anything", PAYROLL).available
