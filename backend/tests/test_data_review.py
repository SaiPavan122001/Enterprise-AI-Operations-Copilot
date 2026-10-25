"""Data-quality safeguards: quarantine reviews bind to an exact link, strict
ingestion, provenance, and the human-decision workflow (validate only)."""

import json

from scripts import link_review
from utils.data_integrity import check_integrity, load_provenance, strict_problems

INC = [{"id": "INC-001", "service": "payroll-service", "severity": "High", "status": "Resolved",
        "title": "t", "root_cause": "r", "deployment_id": "DEP-2"}]
DEPS = [{"deployment_id": "DEP-1", "service": "payroll-service", "time": "2026-05-01T10:00:00", "change": "c"},
        {"deployment_id": "DEP-2", "service": "auth-service", "time": "2026-05-02T10:00:00", "change": "c"},
        {"deployment_id": "DEP-3", "service": "leave-service", "time": "2026-05-03T10:00:00", "change": "c"}]
LOGS = ["2026-05-01 10:00:00 payroll-service ERROR boom"]
REVIEW = {"INC-001": {"incident_id": "INC-001", "referenced_deployment_id": "DEP-2",
                      "status": "quarantined_pending_human_review"}}


class TestQuarantineReviewBinding:
    def test_reviewed_link_is_quarantined_not_error(self):
        r = check_integrity(INC, DEPS, LOGS, set(), REVIEW)
        assert r.ok and "INC-001" in r.quarantined_links

    def test_changing_to_another_bad_link_does_not_inherit_the_review(self):
        changed = [dict(INC[0], deployment_id="DEP-3")]
        r = check_integrity(changed, DEPS, LOGS, set(), REVIEW)
        assert not r.ok
        assert [i.code for i in r.by_severity("error")] == ["stale_quarantine_review"]

    def test_fixing_the_link_verifies_it(self):
        fixed = [dict(INC[0], deployment_id="DEP-1")]
        r = check_integrity(fixed, DEPS, LOGS, set(), REVIEW)
        assert r.ok and "INC-001" in r.verified_links and not r.quarantined_links


class TestStrictIngestion:
    def test_reviewed_quarantine_refused_in_strict_mode(self):
        r = check_integrity(INC, DEPS, LOGS, set(), REVIEW)
        problems = strict_problems(r, REVIEW, {"status": "real"})
        assert any("INC-001" in p and "quarantined" in p for p in problems)

    def test_unconfirmed_provenance_refused(self):
        clean = [dict(INC[0], deployment_id="DEP-1")]
        r = check_integrity(clean, DEPS, LOGS, set(), {})
        assert any("provenance" in p for p in strict_problems(r, {}, {"status": "unconfirmed"}))
        assert strict_problems(r, {}, {"status": "real"}) == []

    def test_repository_data_is_not_strict_clean(self):
        from utils.data_integrity import get_integrity_report
        assert strict_problems(get_integrity_report())          # 8 links + logs + provenance

    def test_provenance_defaults_to_unconfirmed(self, tmp_path):
        p = tmp_path / "review.json"
        p.write_text(json.dumps({"dataset_assessment": {"provenance": {"status": "maybe"}}}), encoding="utf-8")
        assert load_provenance(p)["status"] == "unconfirmed"
        assert load_provenance(tmp_path / "missing.json")["status"] == "unconfirmed"


def row(**kw):
    base = {"incident_id": "INC-008", "decision": "", "new_deployment_id": "", "reviewer": "", "source": "", "notes": ""}
    base.update(kw)
    return base


class TestReviewerDecisions:
    """Against the repository data: INC-008 is auth-service, quarantined on DEP-108 (payroll)."""

    def test_empty_decision_is_pending_never_none(self):
        assert link_review.plan([row()]) == ([], [])

    def test_none_requires_reviewer_and_source(self):
        changes, errors = link_review.plan([row(decision="none")])
        assert not changes and "reviewer and a source" in errors[0]

    def test_confirmed_none_is_a_change(self):
        changes, errors = link_review.plan([row(decision="none", reviewer="data owner", source="CHG-1")])
        assert not errors and changes[0]["to"] is None

    def test_replacement_must_verify(self):
        changes, errors = link_review.plan([row(decision="replace", new_deployment_id="DEP-101",
                                                reviewer="owner", source="ticket")])
        assert not changes and "quarantined again" in errors[0]          # DEP-101 is payroll

    def test_valid_replacement(self):
        changes, errors = link_review.plan([row(decision="replace", new_deployment_id="DEP-116",
                                                reviewer="owner", source="ticket")])
        assert not errors and changes[0]["to"] == "DEP-116"

    def test_unknown_deployment_and_decision_rejected(self):
        _, errors = link_review.plan([row(decision="replace", new_deployment_id="DEP-999", reviewer="o", source="s"),
                                      row(decision="maybe")])
        assert len(errors) == 2
