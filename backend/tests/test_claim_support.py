"""Runtime claim-support verification: deterministic record-membership checks
(always) and the semantic NLI verifier (tests marked ``nli`` load the local model)."""

import pytest

from agents import claim_verifier as cv
from agents import rca_structured as rs
from models.evidence import DeploymentEvidence, EvidenceBundle, EvidenceValidation, IncidentEvidence

INC = IncidentEvidence(incident_id="INC-014", service="reporting-service", severity="High", status="Resolved",
                       title="Dashboard metrics incorrect", root_cause="ETL job failure")
DEP = DeploymentEvidence(deployment_id="DEP-114", service="reporting-service", time="2026-05-14T10:00:00",
                         change="ETL pipeline update", incident_id="INC-014")
B = EvidenceBundle(question="Why are dashboard metrics incorrect?", incident_evidence=[INC], deployment_evidence=[DEP])
V = EvidenceValidation(evidence_strength="MEDIUM")


def answer(**kw):
    base = {"answer_status": "answered",
            "summary": "Dashboard metrics were incorrect because of an ETL job failure [INC-014].",
            "confirmed_facts": [{"statement": "INC-014 recorded incorrect dashboard metrics.", "refs": ["INC-014"]}],
            "root_cause": {"status": "determined", "statement": "ETL job failure", "refs": ["INC-014"]},
            "conclusions": [], "hypotheses": [], "impact": [], "contributing_factors": [],
            "limitations": [], "unknowns": [], "recommended_remediation": [], "preventive_actions": [],
            "confidence": "MEDIUM", "confidence_reason": ""}
    base.update(kw)
    return base


class TestDeterministicChecks:
    def test_service_mismatch_removed(self):
        clean, issues = rs.validate(answer(confirmed_facts=[
            {"statement": "INC-014 occurred on the payroll-service.", "refs": ["INC-014"]}]), B, V, [])
        assert clean["confirmed_facts"] == []
        assert any("payroll-service" in i and "removed claim" in i for i in issues)

    def test_severity_mismatch_removed(self):
        clean, issues = rs.validate(answer(impact=[
            {"statement": "INC-014 was a critical incident.", "refs": ["INC-014"]}]), B, V, [])
        assert clean["impact"] == []
        assert any("severity" in i for i in issues)

    def test_matching_service_and_severity_kept(self):
        clean, _ = rs.validate(answer(confirmed_facts=[
            {"statement": "INC-014 was a high-severity incident on the reporting-service.", "refs": ["INC-014"]}]),
            B, V, [])
        assert len(clean["confirmed_facts"]) == 1

    def test_deployment_service_counts_as_cited(self):
        assert cv.deterministic_problems("DEP-114 changed the reporting-service ETL pipeline.", ["DEP-114"], B) == []

    def test_summary_sentence_with_wrong_service_removed(self):
        clean, issues = rs.validate(answer(
            summary="Dashboard metrics were incorrect because of an ETL job failure [INC-014]. "
                    "The auth-service was also affected [INC-014]."), B, V, [])
        assert "auth-service" not in clean["summary"]
        assert any(i.startswith("summary: sentence removed") for i in issues)

    def test_invented_figures_downgraded_to_hypothesis(self):
        clean, issues = rs.validate(answer(impact=[
            {"statement": "INC-014 affected 4,200 users for 3 hours.", "refs": ["INC-014"]}]), B, V, [])
        assert clean["impact"] == []
        assert any("4,200" in h["statement"] for h in clean["hypotheses"])
        assert any("figures not in the evidence (4,200, 3)" in i for i in issues)

    def test_figures_present_in_the_evidence_are_kept(self):
        clean, _ = rs.validate(answer(confirmed_facts=[
            {"statement": "DEP-114 was deployed at 10:00 on 2026-05-14.", "refs": ["DEP-114"]}]), B, V, [])
        assert len(clean["confirmed_facts"]) == 1

    def test_deployment_date_from_iso_timestamp_is_evidence(self):
        # Regression: "2026-05-14T10:00:00" has no word boundary before "T", so the
        # date was not recognised and true claims stating it were removed.
        assert "2026-05-14" in rs.evidence_dates(B, [])

    def test_service_from_evidence_notes_is_allowed(self):
        v = EvidenceValidation(evidence_strength="MEDIUM",
                               missing_evidence=["Deployment link not used: DEP-120 belongs to leave-service"])
        clean, _ = rs.validate(answer(confirmed_facts=[
            {"statement": "The link DEP-120 for INC-014 is quarantined because it belongs to leave-service.",
             "refs": ["INC-014"]}]), B, v, [])
        assert len(clean["confirmed_facts"]) == 1

    def test_off_disables_all_checks(self, monkeypatch):
        monkeypatch.setattr(cv.settings, "CLAIM_VERIFIER", "off")
        clean, _ = rs.validate(answer(confirmed_facts=[
            {"statement": "INC-014 occurred on the payroll-service.", "refs": ["INC-014"]}]), B, V, [])
        assert len(clean["confirmed_facts"]) == 1

    def test_model_unavailable_is_reported_not_silent(self, monkeypatch):
        monkeypatch.setattr(cv.settings, "CLAIM_VERIFIER", "nli")
        monkeypatch.setattr(cv, "_load", lambda: None)
        clean, issues = rs.validate(answer(), B, V, [])
        assert any("semantic verifier unavailable" in i for i in issues)
        assert len(clean["confirmed_facts"]) == 1           # nothing removed for lack of a model


@pytest.mark.nli
class TestSemanticVerifier:
    """Adversarial claims, each citing the right record (valid provenance)."""

    def test_swapped_root_cause_removed(self):
        clean, issues = rs.validate(answer(confirmed_facts=[
            {"statement": "The recorded root cause of INC-014 was a cron job configuration error.",
             "refs": ["INC-014"]}]), B, V, [])
        assert clean["confirmed_facts"] == []
        assert any("contradicted" in i for i in issues)

    def test_negated_statement_still_not_sent_to_nli(self):
        # Negations are still kept away from the NLI model (it judged true absence
        # statements "contradicted"); negated CAUSES are now caught deterministically.
        res = cv.verify_claims([{"statement": "The root cause of INC-014 was not an ETL job failure.",
                                 "refs": ["INC-014"]}], B)
        assert res[0]["semantic"] == cv.SKIPPED and res[0]["deterministic"]

    def test_true_absence_statement_kept(self):
        clean, issues = rs.validate(answer(confirmed_facts=[
            {"statement": "No log lines on reporting-service corroborate INC-014.", "refs": ["INC-014"]}]), B, V, [])
        assert len(clean["confirmed_facts"]) == 1, issues

    def test_true_compound_restatement_kept(self):
        clean, issues = rs.validate(answer(confirmed_facts=[
            {"statement": "INC-014 on reporting-service was a High severity incident titled 'Dashboard metrics "
                          "incorrect' with a recorded root cause of ETL job failure.", "refs": ["INC-014"]}]), B, V, [])
        assert len(clean["confirmed_facts"]) == 1, issues

    def test_supported_paraphrase_kept(self):
        clean, issues = rs.validate(answer(confirmed_facts=[
            {"statement": "An ETL job failure was recorded as the root cause of INC-014.", "refs": ["INC-014"]}]),
            B, V, [])
        assert len(clean["confirmed_facts"]) == 1, issues

    def test_contradicted_root_cause_replaced_with_recorded_cause(self):
        clean, issues = rs.validate(answer(root_cause={"status": "determined",
                                                       "statement": "A cron job configuration error",
                                                       "refs": ["INC-014"]}), B, V, [])
        assert clean["root_cause"]["statement"] == "ETL job failure"
        assert any(i.startswith("root_cause: replaced") for i in issues)

    def test_conclusion_inference_not_downgraded_when_neutral(self):
        clean, _ = rs.validate(answer(conclusions=[
            {"statement": "Monitoring of the ETL job would likely have detected the failure earlier.",
             "refs": ["INC-014"]}]), B, V, [])
        assert len(clean["conclusions"]) == 1


class TestRecordContradictions:
    """Round 6: deterministic checks for claims that contradict the cited record.
    INC-014 (fixture B): Resolved, High, root cause "ETL job failure", verified DEP-114."""

    def kept(self, statement, refs=("INC-014",), section="confirmed_facts"):
        clean, issues = rs.validate(answer(**{section: [{"statement": statement, "refs": list(refs)}]}), B, V, [])
        return len(clean[section]) == 1, issues

    @pytest.mark.parametrize("statement", [
        "INC-014 is still unresolved.",
        "INC-014 remains open.",
        "INC-014 has not yet been resolved.",
    ])
    def test_wrong_status_removed(self, statement):
        ok, issues = self.kept(statement)
        assert not ok and any("unresolved" in i for i in issues)

    @pytest.mark.parametrize("statement", [
        "The root cause of INC-014 was not an ETL job failure.",
        "An ETL job failure was not the root cause of INC-014.",
        "INC-014 was not caused by an ETL job failure.",
        "INC-014 did not result from an ETL job failure.",
    ])
    def test_negated_recorded_cause_removed(self, statement):
        ok, issues = self.kept(statement)
        assert not ok and any("negates the recorded root cause" in i for i in issues)

    @pytest.mark.parametrize("statement", [
        "No root cause was recorded for INC-014.",
        "The root cause of INC-014 is unknown.",
        "INC-014 has no recorded root cause.",
        "INC-014 has no deployment linked to it.",
    ])
    def test_false_absence_removed(self, statement):
        ok, _ = self.kept(statement)
        assert not ok

    def test_other_incidents_cause_removed(self):
        ok, issues = self.kept("The recorded root cause of INC-014 was a cron job configuration error.")
        assert not ok and any("INC-020" in i for i in issues)

    def test_other_incidents_title_removed(self):
        ok, issues = self.kept('INC-014 recorded the problem "Scheduled reports not generated".')
        assert not ok and any("INC-020" in i for i in issues)

    @pytest.mark.parametrize("statement,refs", [
        # true statements that the round-6 rules must keep (several are real answer sentences)
        ("INC-014 has been resolved.", ("INC-014",)),
        ("No log lines on reporting-service corroborate the ETL job failure in INC-014.", ("INC-014",)),
        ("There is no evidence that the ETL job failure in INC-014 caused any other incident.", ("INC-014",)),
        ("The root cause of INC-014 was an ETL job failure, not a deployment.", ("INC-014",)),
        ("DEP-114 changed the ETL pipeline and is linked to INC-014.", ("INC-014", "DEP-114")),
    ])
    def test_true_statements_kept(self, statement, refs):
        ok, issues = self.kept(statement, refs)
        assert ok, issues


def test_cited_deployment_vocabulary_is_not_another_incidents_record():
    # Real-answer false positive: "ingress configuration change" is DEP-115's own
    # recorded change, not INC-005's "Ingress configuration error".
    inc = IncidentEvidence(incident_id="INC-015", service="payroll-service", severity="Critical", status="Resolved",
                           title="Payroll API returning 500 errors", root_cause="Schema version mismatch")
    dep = DeploymentEvidence(deployment_id="DEP-115", service="payroll-service", time="2026-05-16T10:45:00",
                             change="Ingress configuration change", incident_id="INC-015")
    b = EvidenceBundle(question="q", incident_evidence=[inc], deployment_evidence=[dep])
    assert cv.deterministic_problems("INC-015 is linked to DEP-115, an ingress configuration change.",
                                     ["INC-015", "DEP-115"], b) == []


def test_cause_containing_the_word_missing_is_not_an_absence_claim():
    # Dev false positive: INC-007's recorded cause is "Missing database indexes".
    inc = IncidentEvidence(incident_id="INC-007", service="reporting-service", severity="Medium", status="Resolved",
                           title="Reports loading slowly", root_cause="Missing database indexes")
    b = EvidenceBundle(question="q", incident_evidence=[inc])
    assert cv.deterministic_problems("The recorded root cause of INC-007 was missing database indexes.",
                                     ["INC-007"], b) == []


@pytest.mark.parametrize("statement", [
    # Unseen-run false positives (round 6): statements about ANOTHER, unmatched part of the question.
    "The root cause of the stuck leave approval workflow in the leave service is not determined from the "
    "available records.",
    "No incident record describes the impact of the missing database indexes on the reporting-service.",
])
def test_absence_about_an_unmatched_incident_is_kept(statement):
    clean, issues = rs.validate(answer(confirmed_facts=[{"statement": statement, "refs": ["INC-014"]}]), B, V, [])
    assert len(clean["confirmed_facts"]) == 1, issues
