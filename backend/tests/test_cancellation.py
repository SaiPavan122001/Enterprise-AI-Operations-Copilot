"""Request cancellation propagates through every stage, the LLM layer (before
each attempt and during backoff) and the API (disconnect -> token). No network."""

import asyncio
import threading
import time

import pytest

from agents import llm_client
from agents.llm_client import LLMResponse
from utils import cancellation
from utils.cancellation import CancellationToken, InvestigationCancelled
from workflows import rca_graph
from workflows.rca_graph import NODE_STAGE_IDS

STAGES = list(NODE_STAGE_IDS)


class CancelAt(CancellationToken):
    """Cancels itself when the workflow checks ``target``; records every check."""

    def __init__(self, target):
        super().__init__()
        self.target, self.checked = target, []

    def raise_if_cancelled(self, stage):
        self.checked.append(stage)
        if stage == self.target:
            self.cancel("test")
        super().raise_if_cancelled(stage)


@pytest.fixture
def offline_graph(monkeypatch):
    monkeypatch.setattr(rca_graph, "incident_agent", lambda q, **k: {"incidents": [], "scores": []})


@pytest.mark.parametrize("stage", STAGES)
def test_cancel_at_each_stage_stops_the_workflow(offline_graph, stage):
    token = CancelAt(stage)
    with pytest.raises(InvestigationCancelled) as exc:
        rca_graph.app.invoke({"question": "Why is payroll failing?", "_cancel": token})
    assert exc.value.stage == stage
    assert token.checked == STAGES[:STAGES.index(stage) + 1]       # no later stage started


def test_uncancelled_token_runs_to_completion(offline_graph):
    token = CancelAt("never")
    state = rca_graph.app.invoke({"question": "Why is payroll failing?", "_cancel": token})
    assert token.checked == STAGES and state["investigation"]["answer_status"]


def test_no_token_behaves_as_before(offline_graph):
    assert rca_graph.app.invoke({"question": "Why is payroll failing?"})["investigation"]


def retry(call, **kw):
    args = dict(provider="openai", max_retries=3, base=5.0, cap=5.0, quota_cooldown=1.0)
    args.update(kw)
    return llm_client.call_with_retry(call, **args)


class TestLLMLayer:
    def test_cancelled_before_attempt_makes_no_call(self):
        token = CancellationToken()
        token.cancel()
        calls = []
        bound = cancellation.bind(token)
        try:
            with pytest.raises(InvestigationCancelled) as exc:
                retry(lambda: calls.append(1) or LLMResponse(text="x", provider="openai", model="m"))
        finally:
            cancellation.unbind(bound)
        assert calls == [] and exc.value.stage == "llm_call"

    def test_cancel_during_backoff_wakes_immediately(self):
        token = CancellationToken()
        calls = []

        def failing():
            calls.append(1)
            # Cancel 0.2 s AFTER the first attempt failed, i.e. during the 5 s backoff.
            # (A timer started before retry() could fire before the first attempt on a
            # slow CI runner, cancelling at the wrong stage.)
            threading.Timer(0.2, token.cancel).start()
            raise TimeoutError("transient")

        bound = cancellation.bind(token)
        t0 = time.monotonic()
        try:
            with pytest.raises(InvestigationCancelled) as exc:
                retry(failing, base=5.0, cap=5.0)
        finally:
            cancellation.unbind(bound)
        assert time.monotonic() - t0 < 2.0          # did not sleep the full backoff
        assert exc.value.stage == "llm_backoff" and calls == [1]

    def test_fail_soft_matcher_does_not_swallow_cancellation(self, monkeypatch):
        from agents import gemini_rca_agent, incident_matcher
        from models.evidence import IncidentEvidence

        def cancelled(*a, **k):
            raise InvestigationCancelled("llm_call")

        monkeypatch.setattr(gemini_rca_agent, "generate_text", cancelled)
        with pytest.raises(InvestigationCancelled):
            incident_matcher.match_incidents("q?", [IncidentEvidence(incident_id="INC-001", service="s")])


class TestAPI:
    def test_disconnect_sets_the_token(self):
        from api.routes import _cancel_on_disconnect

        class Req:
            n = 0

            async def is_disconnected(self):
                self.n += 1
                return self.n >= 2

        token = CancellationToken()
        asyncio.run(_cancel_on_disconnect(Req(), token, interval=0.01))
        assert token.cancelled and token.reason == "client disconnected"

    def test_closing_the_stream_cancels_the_workflow(self, monkeypatch):
        from api import routes

        progressed = []

        class SlowGraph:
            def stream(self, state, stream_mode):
                for stage in STAGES:
                    state["_cancel"].raise_if_cancelled(stage)
                    progressed.append(stage)
                    time.sleep(0.05)
                    yield {stage: {}}

        monkeypatch.setattr(routes, "rca_graph", SlowGraph())
        token = CancellationToken()

        async def consume_two_then_disconnect():
            gen = routes.investigation_events("Why is payroll failing?", token)
            events = [await gen.__anext__(), await gen.__anext__()]
            await gen.aclose()                       # what Starlette does on client disconnect
            await asyncio.sleep(0.3)                 # let the worker reach its next check
            return events

        events = asyncio.run(consume_two_then_disconnect())
        assert events[0].startswith("event: investigation_started")
        assert token.cancelled
        assert len(progressed) < len(STAGES)         # the workflow stopped early

    def test_investigate_returns_cancelled_status(self, monkeypatch):
        from fastapi.testclient import TestClient

        from api import routes
        from app import app
        from config import settings

        monkeypatch.setattr(settings, "AUTH_MODE", "disabled")

        class Cancelled:
            def invoke(self, state):
                raise InvestigationCancelled("rca_generation", "client disconnected")

        monkeypatch.setattr(routes, "rca_graph", Cancelled())
        r = TestClient(app).post("/investigate", json={"question": "Why is payroll failing?"})
        assert r.status_code == 499 and r.json()["message"] == "Investigation cancelled."


class TestRealGraphThroughHTTP:
    """Regression: the API endpoints with the REAL compiled workflow (only retrieval
    stubbed) through the full middleware stack must complete normally - no false
    cancellation from the disconnect watcher."""

    @pytest.fixture
    def client(self, offline_graph, monkeypatch):
        from fastapi.testclient import TestClient

        from app import app
        from config import settings

        monkeypatch.setattr(settings, "AUTH_MODE", "disabled")
        return TestClient(app)

    def test_investigate_completes(self, client):
        r = client.post("/investigate", json={"question": "Why is payroll generation failing?"},
                        headers={"X-Request-ID": "reg-1"})
        assert r.status_code == 200 and r.headers["x-request-id"] == "reg-1"
        assert r.json()["investigation"]["answer_status"]

    def test_stream_emits_every_stage_and_completes(self, client):
        r = client.post("/investigate/stream", json={"question": "Why is payroll generation failing?"})
        events = [line[len("event: "):] for line in r.text.splitlines() if line.startswith("event: ")]
        assert events[0] == "investigation_started" and events[-1] == "investigation_completed"
        assert [e for e in events if e.endswith("_completed") and e != "investigation_completed"] == \
            [f"{s}_completed" for s in STAGES]
