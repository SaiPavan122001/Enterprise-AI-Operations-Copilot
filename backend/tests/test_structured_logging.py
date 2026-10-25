"""Structured logging: context fields on every record, JSON format, request IDs,
credential redaction, and no question text in the logs."""

import json
import logging

import pytest

from utils import log_context
from utils.log_context import ContextFilter, JsonFormatter, redact, request_id_from


def record(msg="hello", **extra):
    r = logging.LogRecord("t", logging.INFO, __file__, 1, msg, None, None)
    for k, v in extra.items():
        setattr(r, k, v)
    ContextFilter().filter(r)
    return r


class TestFormatter:
    def test_json_has_context_and_extra_fields(self):
        with log_context.context(request_id="req1", investigation_id="inv1", stage="rca_generation",
                                 principal="ops"):
            out = json.loads(JsonFormatter().format(record(provider="openai", model="m", duration_ms=12,
                                                           outcome="ok")))
        assert out["request_id"] == "req1" and out["investigation_id"] == "inv1"
        assert out["stage"] == "rca_generation" and out["principal"] == "ops"
        assert out["provider"] == "openai" and out["duration_ms"] == 12 and out["outcome"] == "ok"

    def test_defaults_outside_a_request(self):
        out = json.loads(JsonFormatter().format(record()))
        assert out["request_id"] == "-" and out["stage"] == "-"

    # Fake credentials, assembled at runtime so secret scanners do not flag the source.
    @pytest.mark.parametrize("secret", ["sk-" + "proj-abcdefghijklmnop", "AI" + "zaSyA1234567890abcdefghijklmn",
                                        "Bearer " + "abcdefghijkl123", "sk-" + "lf-1234abcd-5678",
                                        "pk-" + "lf-1234abcd-5678"])
    def test_credentials_redacted(self, secret):
        assert secret not in redact(f"calling with {secret} now")
        assert secret not in JsonFormatter().format(record(f"key={secret}"))

    def test_request_id_header_validation(self):
        assert request_id_from("abc-123") == "abc-123"
        assert request_id_from("bad id with spaces\n") != "bad id with spaces\n"
        assert len(request_id_from(None)) == 16
        assert request_id_from("x" * 200) != "x" * 200


class TestRequestLogging:
    @pytest.fixture
    def app_client(self, monkeypatch):
        from fastapi.testclient import TestClient

        from api import routes
        from app import app
        from config import settings

        monkeypatch.setattr(settings, "AUTH_MODE", "disabled")

        class Graph:
            def invoke(self, state):
                logging.getLogger("workflows.rca_graph").info("inside workflow")
                raise RuntimeError("boom")

        monkeypatch.setattr(routes, "rca_graph", Graph())
        return TestClient(app)

    def test_request_id_returned_and_on_workflow_logs(self, app_client, caplog):
        caplog.set_level(logging.INFO)
        for h in logging.getLogger().handlers:
            h.addFilter(ContextFilter())
        r = app_client.post("/investigate", json={"question": "Why is the secret payroll thing failing?"},
                            headers={"X-Request-ID": "trace-42"})
        assert r.headers["x-request-id"] == "trace-42"
        inside = [x for x in caplog.records if x.getMessage() == "inside workflow"]
        assert inside and inside[0].request_id == "trace-42"
        assert inside[0].investigation_id not in ("-", "")          # copied into the worker thread
        assert inside[0].principal == "local-dev"

    def test_question_text_never_logged(self, app_client, caplog):
        caplog.set_level(logging.DEBUG)
        app_client.post("/investigate", json={"question": "Why is the secret payroll thing failing?"})
        assert not any("secret payroll" in x.getMessage() for x in caplog.records)
        access = [x for x in caplog.records if getattr(x, "path", None) == "/investigate"]
        assert access and access[0].status_code == 500 and access[0].duration_ms >= 0
