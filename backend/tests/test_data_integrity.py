"""Regression tests for incident / deployment / service / log integrity."""

import json

import pytest

from agents.deployment_agent import deployment_link_status, investigate_deployments
from agents.log_agent import corroborating_logs
from config import DATA_DIR
from models.evidence import DeploymentEvidence, IncidentEvidence
from utils.data_integrity import check_integrity, load_dependencies, load_review_decisions

DEPLOYMENTS = [
    {"deployment_id": "DEP-1", "service": "payroll-service", "time": "2026-05-02T10:00:00",
     "change": "Database schema migration"},
    {"deployment_id": "DEP-2", "service": "auth-service", "time": "2026-05-03T10:00:00",
     "change": "JWT authentication upgrade"},
]
LOGS = [
    "2026-05-02 10:30:00 payroll-service ERROR migration failed: salary_amount column missing",
    "2026-05-03 10:30:00 auth-service ERROR JWT signing key rejected",
]


def incident(iid="INC-1", service="payroll-service", dep="DEP-1", **kw):
    base = {"id": iid, "service": service, "severity": "High", "status": "Resolved",
            "title": "Payroll generation failing",
            "root_cause": "Database migration missing salary_amount column", "deployment_id": dep}
    base.update(kw)
    return base


class TestCheckIntegrity:
    def test_valid_records(self):
        r = check_integrity([incident()], DEPLOYMENTS, LOGS)
        assert r.ok and r.verified_links["INC-1"]["deployment_id"] == "DEP-1"
        assert not r.quarantined_links

    def test_incorrect_service_reference_is_quarantined(self):
        bad = incident(dep="DEP-2")   # payroll incident -> auth deployment
        r = check_integrity([bad], DEPLOYMENTS, LOGS,
                            review_decisions={"INC-1": {"referenced_deployment_id": "DEP-2"}})
        assert r.quarantined_links["INC-1"].code == "deployment_service_mismatch"
        assert "INC-1" not in r.verified_links
        assert r.ok   # reviewed quarantine does not block ingestion

    def test_unreviewed_quarantine_fails_ingestion(self):
        r = check_integrity([incident(dep="DEP-2")], DEPLOYMENTS, LOGS)
        assert not r.ok
        assert r.by_severity("error")[0].code == "unreviewed_quarantine"

    def test_missing_deployment_is_quarantined(self):
        r = check_integrity([incident(dep="DEP-999")], DEPLOYMENTS, LOGS,
                            review_decisions={"INC-1": {"referenced_deployment_id": "DEP-999"}})
        assert r.quarantined_links["INC-1"].code == "deployment_missing"

    def test_documented_dependency_is_accepted(self):
        r = check_integrity([incident(dep="DEP-2")], DEPLOYMENTS, LOGS,
                            dependencies={("payroll-service", "auth-service")})
        assert r.ok and r.verified_links["INC-1"]["deployment_id"] == "DEP-2"
        assert r.by_severity("info")[0].code == "cross_service_dependency"

    def test_missing_logs_for_service_warns(self):
        r = check_integrity([incident(service="leave-service", dep=None)], DEPLOYMENTS, LOGS)
        assert any(i.code == "no_logs_for_service" and i.record_id == "leave-service"
                   for i in r.by_severity("warning"))

    def test_non_service_specific_log_message_warns(self):
        logs = [f"2026-05-02 10:0{i}:00 {s} ERROR SMTP quota exceeded"
                for i, s in enumerate(["a-service", "b-service", "c-service"])]
        r = check_integrity([incident()], DEPLOYMENTS, logs)
        assert "SMTP quota exceeded" in r.non_specific_log_messages

    def test_duplicate_ids_and_missing_fields_are_errors(self):
        r = check_integrity([incident(), incident(title="")], DEPLOYMENTS, LOGS)
        codes = {i.code for i in r.by_severity("error")}
        assert {"duplicate_incident_id", "incident_missing_fields"} <= codes

    def test_undocumented_dependency_entry_rejected(self, tmp_path):
        p = tmp_path / "deps.json"
        p.write_text(json.dumps({"dependencies": [{"service": "a", "depends_on": "b"}]}))
        with pytest.raises(ValueError, match="source"):
            load_dependencies(p)


class TestRealDataset:
    """The shipped data: exactly the 8 known cross-service links are quarantined,
    every one is in the manual review queue, and nothing else is rewritten."""

    KNOWN = {"INC-008", "INC-009", "INC-010", "INC-011", "INC-017", "INC-018", "INC-019", "INC-020"}

    def _report(self):
        from utils.data_store import get_deployments, get_logs

        incidents = json.loads((DATA_DIR / "incidents.json").read_text(encoding="utf-8"))
        return check_integrity(incidents, get_deployments(), get_logs(),
                               load_dependencies(), load_review_decisions())

    def test_known_mismatches_quarantined_and_reviewed(self):
        r = self._report()
        assert r.ok
        assert set(r.quarantined_links) == self.KNOWN
        assert set(load_review_decisions()) == self.KNOWN
        assert len(r.verified_links) == 12

    def test_source_data_not_modified(self):
        incidents = json.loads((DATA_DIR / "incidents.json").read_text(encoding="utf-8"))
        assert {i["id"]: i["deployment_id"] for i in incidents}["INC-017"] == "DEP-117"


class TestJoins:
    INC = IncidentEvidence(incident_id="INC-1", service="payroll-service", deployment_id="DEP-1",
                           title="Payroll generation failing",
                           root_cause="Database migration missing salary_amount column")

    def test_link_status(self):
        assert deployment_link_status(self.INC, DEPLOYMENTS, set())[0] == "verified"
        wrong = self.INC.model_copy(update={"deployment_id": "DEP-2"})
        assert deployment_link_status(wrong, DEPLOYMENTS, set())[0] == "quarantined"
        assert deployment_link_status(wrong, DEPLOYMENTS, {("payroll-service", "auth-service")})[0] \
            == "documented_dependency"
        missing = self.INC.model_copy(update={"deployment_id": "DEP-404"})
        assert deployment_link_status(missing, DEPLOYMENTS, set())[0] == "missing"

    def test_quarantined_link_not_joined(self, monkeypatch):
        monkeypatch.setattr("agents.deployment_agent.get_deployments", lambda: DEPLOYMENTS)
        monkeypatch.setattr("agents.deployment_agent.load_dependencies", lambda: set())
        wrong = self.INC.model_copy(update={"deployment_id": "DEP-2"})
        assert investigate_deployments([wrong]) == []
        ok = investigate_deployments([self.INC])
        assert ok[0].deployment_id == "DEP-1" and ok[0].incident_id == "INC-1"

    def test_documented_dependency_joined(self, monkeypatch):
        monkeypatch.setattr("agents.deployment_agent.get_deployments", lambda: DEPLOYMENTS)
        monkeypatch.setattr("agents.deployment_agent.load_dependencies",
                            lambda: {("payroll-service", "auth-service")})
        wrong = self.INC.model_copy(update={"deployment_id": "DEP-2"})
        assert investigate_deployments([wrong])[0].link_status == "documented_dependency"


class TestLogCorroboration:
    INC = TestJoins.INC
    DEP = DeploymentEvidence(deployment_id="DEP-1", service="payroll-service",
                             time="2026-05-02T10:00:00", change="Database schema migration",
                             incident_id="INC-1")

    def _logs(self, monkeypatch, lines):
        monkeypatch.setattr("agents.log_agent.get_logs", lambda: lines)

    def test_same_service_matching_line_in_window_corroborates(self, monkeypatch):
        self._logs(monkeypatch, LOGS)
        out = corroborating_logs([self.INC], [self.DEP], dependencies=set())
        assert [e.service for e in out] == ["payroll-service"] and out[0].incident_id == "INC-1"

    def test_other_service_never_joined(self, monkeypatch):
        self._logs(monkeypatch, ["2026-05-02 10:30:00 auth-service ERROR salary_amount column missing"])
        assert corroborating_logs([self.INC], [self.DEP], dependencies=set()) == []

    def test_outside_time_window_not_joined(self, monkeypatch):
        self._logs(monkeypatch, ["2026-05-09 10:30:00 payroll-service ERROR salary_amount column missing"])
        assert corroborating_logs([self.INC], [self.DEP], dependencies=set()) == []

    def test_unrelated_message_not_joined(self, monkeypatch):
        self._logs(monkeypatch, ["2026-05-02 10:30:00 payroll-service ERROR disk quota exceeded"])
        assert corroborating_logs([self.INC], [self.DEP], dependencies=set()) == []

    def test_message_on_many_services_not_joined(self, monkeypatch):
        lines = [f"2026-05-02 10:3{i}:00 {s} ERROR salary_amount column missing"
                 for i, s in enumerate(["payroll-service", "auth-service", "leave-service"])]
        self._logs(monkeypatch, lines)
        assert corroborating_logs([self.INC], [self.DEP], dependencies=set()) == []

    def test_missing_logs_returns_empty(self, monkeypatch):
        self._logs(monkeypatch, [])
        assert corroborating_logs([self.INC], [self.DEP], dependencies=set()) == []

    def test_documented_dependency_service_logs_joined(self, monkeypatch):
        self._logs(monkeypatch, ["2026-05-02 10:30:00 auth-service ERROR salary_amount column missing"])
        out = corroborating_logs([self.INC], [self.DEP], dependencies={("payroll-service", "auth-service")})
        assert len(out) == 1


class TestIngestionHardening:
    def _collection(self):
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, VectorParams

        q = QdrantClient(":memory:")
        q.create_collection("t", vectors_config=VectorParams(size=3, distance=Distance.COSINE))
        return q

    def _points(self, ids):
        from qdrant_client.models import PointStruct

        return [PointStruct(id=i, vector=[1.0, 0.0, 0.0], payload={"n": i}) for i in ids]

    def test_repeated_ingestion_is_idempotent(self):
        from vector_store.qdrant_setup import sync_points

        q = self._collection()
        first = sync_points(q, "t", self._points([1, 2, 3]))
        second = sync_points(q, "t", self._points([1, 2, 3]))
        assert first["stored"] == second["stored"] == 3 and second["stale_removed"] == 0

    def test_removed_source_record_is_deleted_not_left_stale(self):
        from vector_store.qdrant_setup import sync_points

        q = self._collection()
        sync_points(q, "t", self._points([1, 2, 3]))
        out = sync_points(q, "t", self._points([1, 2]))
        assert out == {"upserted": 2, "stale_removed": 1, "stored": 2}

    def test_invalid_deployment_timestamp_is_error(self):
        deps = [dict(DEPLOYMENTS[0], time="2026-13-45T99:00:00")]
        r = check_integrity([incident()], deps, LOGS)
        assert any(i.code == "deployment_bad_time" for i in r.by_severity("error"))

    def test_invalid_log_timestamp_is_flagged(self):
        r = check_integrity([incident()], DEPLOYMENTS, LOGS + ["2026-02-31 10:00:00 payroll-service ERROR x"])
        assert any(i.code == "unparseable_log_lines" for i in r.by_severity("warning"))

    def test_wrong_types_are_errors(self):
        r = check_integrity([incident(severity=3)], DEPLOYMENTS, LOGS)
        assert any(i.code == "incident_bad_type" for i in r.by_severity("error"))

    def test_unknown_severity_and_duplicate_content_warn(self):
        a = incident()
        b = incident(iid="INC-2", severity="Sev1")
        r = check_integrity([a, b], DEPLOYMENTS, LOGS)
        codes = {i.code for i in r.by_severity("warning")}
        assert {"unknown_severity", "possible_duplicate_incident"} <= codes

    def test_report_is_written(self, tmp_path):
        from utils.data_integrity import write_report

        p = write_report(check_integrity([incident()], DEPLOYMENTS, LOGS), tmp_path / "r.json")
        data = json.loads(open(p, encoding="utf-8").read())
        assert data["ok"] is True and data["verified_links"] == ["INC-1"]

    def test_health_exposes_integrity_status(self):
        from fastapi.testclient import TestClient
        from app import app

        body = TestClient(app).get("/health").json()
        assert body["data_integrity"]["quarantined_links"] == 8
        assert body["data_integrity"]["ok"] is True
