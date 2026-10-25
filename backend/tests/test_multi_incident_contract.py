"""Multi-incident answer contract: per-incident findings, relationship status
enforced by code, no inter-incident causal link stated as fact. No network."""

import pytest

from agents import rca_structured as rs
from models.evidence import DeploymentEvidence, EvidenceBundle, EvidenceValidation, IncidentEvidence

ETL = IncidentEvidence(incident_id="INC-014", service="reporting-service", title="Dashboard metrics incorrect",
                       root_cause="ETL job failure", severity="High")
POOL = IncidentEvidence(incident_id="INC-013", service="employee-service", title="Profile updates not saving",
                        root_cause="Database connection pool exhaustion", severity="Medium")
PAY = IncidentEvidence(incident_id="INC-001", service="payroll-service", title="Payroll generation failing",
                       root_cause="Database migration missing salary_amount column", deployment_id="DEP-101")
PAY2 = IncidentEvidence(incident_id="INC-015", service="payroll-service", title="Payroll API returning 500 errors",
                        root_cause="Schema version mismatch", deployment_id="DEP-101")
V = EvidenceValidation(evidence_strength="MEDIUM")


def bundle(*incs, deps=()):
    return EvidenceBundle(question="How did INC-014 affect INC-013?", incident_evidence=list(incs),
                          deployment_evidence=list(deps))


def answer(**kw):
    base = {"answer_status": "answered",
            "summary": "INC-014 recorded incorrect dashboard metrics from an ETL job failure [INC-014]. "
                       "INC-013 recorded profile updates not saving from connection pool exhaustion [INC-013].",
            "confirmed_facts": [{"statement": "INC-014 records an ETL job failure.", "refs": ["INC-014"]}],
            "root_cause": {"status": "determined", "statement": "ETL job failure; connection pool exhaustion",
                           "refs": ["INC-014", "INC-013"]},
            "conclusions": [], "hypotheses": [], "impact": [], "contributing_factors": [],
            "limitations": [], "unknowns": [], "recommended_remediation": [], "preventive_actions": [],
            "confidence": "MEDIUM", "confidence_reason": "", "question_focus": "relationship",
            "per_incident": [{"incident_id": "INC-014", "statement": "ETL job failure.", "refs": ["INC-014"]},
                             {"incident_id": "INC-013", "statement": "Pool exhaustion.", "refs": ["INC-013"]}],
            "relationship": {"status": "not_established", "statement": "No record connects INC-014 and INC-013.",
                             "refs": ["INC-014", "INC-013"]}}
    base.update(kw)
    return base


def check(data, b, deps=frozenset()):
    return rs.validate(data, b, V, [], dependencies=set(deps))


class TestDirectCausation:
    def test_causal_link_between_incidents_becomes_hypothesis(self):
        clean, issues = check(answer(conclusions=[
            {"statement": "The ETL failure in INC-014 caused the pool exhaustion in INC-013.",
             "refs": ["INC-014", "INC-013"]}]), bundle(ETL, POOL))
        assert clean["conclusions"] == []
        assert any("INC-013" in h["statement"] for h in clean["hypotheses"])
        assert any("link between incidents" in i for i in issues)

    def test_claimed_documented_relationship_without_record_is_downgraded(self):
        clean, issues = check(answer(relationship={"status": "documented",
                                                   "statement": "INC-014 affected INC-013.", "refs": []}),
                              bundle(ETL, POOL))
        assert clean["relationship"]["status"] == "not_established"
        assert "affected" not in clean["relationship"]["statement"]
        assert any("no record links" in i for i in issues)

    def test_relationship_statement_asserting_link_is_replaced(self):
        clean, issues = check(answer(relationship={"status": "not_established",
                                                   "statement": "INC-014 likely impacted INC-013.", "refs": []}),
                              bundle(ETL, POOL))
        assert clean["relationship"]["statement"] == \
            "The records do not establish a connection between INC-013, INC-014."
        assert any("statement replaced" in i for i in issues)


class TestTemporalCorrelation:
    def test_shared_deployment_is_documented_but_not_causation(self):
        dep = DeploymentEvidence(deployment_id="DEP-101", service="payroll-service", time="2026-05-02T10:03:00",
                                 change="Database schema migration", incident_id="INC-001")
        dep2 = dep.model_copy(update={"incident_id": "INC-015"})
        clean, _ = check(answer(relationship={"status": "documented", "statement": "x", "refs": []},
                                summary="INC-001 failed on a missing column [INC-001]. INC-015 returned 500s "
                                        "from a schema mismatch [INC-015].",
                                per_incident=[], conclusions=[
                                    {"statement": "INC-001 led to INC-015 errors.", "refs": ["INC-001", "INC-015"]}]),
                         bundle(PAY, PAY2, deps=[dep, dep2]))
        assert clean["relationship"]["status"] == "documented"
        assert "DEP-101" in clean["relationship"]["statement"]
        assert "No record states that one incident caused" in clean["relationship"]["statement"]
        assert clean["conclusions"] == []          # causation still only a hypothesis


class TestUnrelatedIncidents:
    def test_answer_that_only_denies_a_link_gets_per_incident_findings(self):
        clean, issues = check(answer(summary="The records do not establish that INC-014 affected INC-013 "
                                             "[INC-014, INC-013]."), bundle(ETL, POOL))
        s = clean["summary"]
        assert s.index("ETL job failure") < s.index("do not establish")
        assert "connection pool exhaustion" in s
        assert any("did not answer individually" in i for i in issues)

    def test_one_sentence_stating_both_causes_is_not_padded(self):
        # Regression: a combined sentence citing both incidents was taken for a
        # relationship sentence and duplicate record text was prepended.
        summary = ("Dashboard metrics were wrong because of an ETL job failure, while profile updates failed "
                   "from database connection pool exhaustion; no record links them [INC-014, INC-013].")
        clean, issues = check(answer(summary=summary), bundle(ETL, POOL))
        assert clean["summary"] == summary
        assert not any("did not answer individually" in i for i in issues)

    def test_relationship_question_summary_states_link_not_established(self):
        # The summary answered each incident but never said whether they are connected.
        data = answer()
        clean, issues = check(data, bundle(ETL, POOL))
        assert clean["summary"].startswith(data["summary"])
        assert clean["summary"].endswith("No record connects INC-014 and INC-013.")
        assert any("stated insufficient evidence" in i for i in issues)

    def test_summary_that_already_denies_the_link_is_not_changed(self):
        data = answer(summary=answer()["summary"] + " No record connects INC-014 and INC-013 [INC-014, INC-013].")
        clean, issues = check(data, bundle(ETL, POOL))
        assert clean["summary"] == data["summary"]
        assert not any("summary" in i for i in issues)

    def test_individual_question_summary_is_not_changed(self):
        data = answer(question_focus="individual", relationship={"status": "not_asked", "statement": "", "refs": []})
        clean, issues = check(data, bundle(ETL, POOL))
        assert clean["summary"] == data["summary"]
        assert not any("summary" in i for i in issues)

    def test_unmatched_part_of_the_question_reported_in_unknowns_not_appended(self):
        # Round 6: appending these notes to the summary made unseen answers read as
        # refusals (the decomposed "parts" were sometimes spurious); they stay in Unknowns.
        note = 'No retrieved incident record describes "printer queue jams", which the question asks about.'
        v = EvidenceValidation(evidence_strength="MEDIUM", missing_evidence=[note])
        clean, issues = rs.validate(answer(question_focus="individual", relationship={"status": "not_asked"}),
                                    bundle(ETL, POOL), v, [], dependencies=set())
        assert note in clean["unknowns"] and note not in clean["summary"]


class TestIndependentImpacts:
    def test_individual_focus_relationship_not_asked(self):
        clean, _ = check(answer(question_focus="individual",
                                relationship={"status": "not_asked", "statement": "", "refs": []}),
                         bundle(ETL, POOL))
        assert clean["relationship"]["status"] == "not_asked"
        assert rs.relationship_text(clean) is None
        md = rs.render_markdown(clean, bundle(ETL, POOL))
        assert "## Per-Incident Findings" in md and "## Relationship Between Incidents" not in md

    def test_missing_per_incident_entry_filled_from_record(self):
        clean, _ = check(answer(per_incident=[{"statement": "ETL job failure.", "refs": ["INC-014"]}]),
                         bundle(ETL, POOL))
        refs = [c["refs"] for c in clean["per_incident"]]
        assert ["INC-013"] in refs
        assert any("Database connection pool exhaustion" in c["statement"] for c in clean["per_incident"])

    def test_relationship_focus_cannot_be_not_asked(self):
        clean, _ = check(answer(relationship={"status": "not_asked", "statement": "", "refs": []}),
                         bundle(ETL, POOL))
        assert clean["relationship"]["status"] == "not_established"


class TestDocumentedDependency:
    def test_documented_service_dependency_is_a_documented_link(self):
        clean, _ = check(answer(relationship={"status": "documented", "statement": "", "refs": []}),
                         bundle(ETL, POOL), deps={("reporting-service", "employee-service")})
        assert clean["relationship"]["status"] == "documented"
        assert "documented dependency" in clean["relationship"]["statement"]


class TestSingleIncidentUnchanged:
    def test_single_incident_prompt_has_no_multi_rules(self):
        b = EvidenceBundle(question="q", incident_evidence=[ETL])
        assert "SEVERAL INCIDENTS" not in rs.build_prompt(b, V, [])
        assert "SEVERAL INCIDENTS" in rs.build_prompt(bundle(ETL, POOL), V, [])

    def test_single_incident_validation_has_no_multi_fields(self):
        clean, _ = rs.validate(answer(), EvidenceBundle(question="q", incident_evidence=[ETL]), V, [],
                               dependencies=set())
        assert "per_incident" not in clean and "relationship" not in clean


@pytest.mark.parametrize("statement,expected", [
    ("The ETL failure in INC-014 caused the pool exhaustion in INC-013.", True),
    ("INC-014 affected INC-013 through stale data.", True),
    ("INC-014 led to INC-013.", True),
    ("INC-014 was caused by an ETL job failure, while INC-013 was caused by pool exhaustion.", False),
    ("INC-014 was caused by an ETL failure; INC-013 by pool exhaustion.", False),
    ("No record shows that INC-014 affected INC-013.", False),
    ("INC-014 did not affect INC-013 according to the records.", False),
    ("INC-014 and INC-013 are unrelated incidents.", False),
    ("The ETL failure caused incorrect metrics [INC-014].", False),     # one incident only
])
def test_incident_link_detector(statement, expected):
    assert rs.asserts_incident_link(statement, {"INC-014", "INC-013"}) is expected
