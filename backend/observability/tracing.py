"""Langfuse tracing for investigations - one trace per investigation with
meaningful stage spans (Langfuse Python SDK v5, OpenTelemetry-based).
Fail-soft: if Langfuse is unavailable, tracing calls become no-ops and the
investigation continues.

Privacy: only the question LENGTH is recorded - never the question, prompt,
evidence or answer - to avoid storing sensitive enterprise data.

v5 API used: ``Langfuse.start_observation(name=, as_type=, metadata=)`` for the
root, ``span.start_observation`` for children, ``span.update`` / ``span.end``.
Each span is ended exactly once (by ``end_stage`` / ``end``).
"""

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

try:
    from observability.langfuse_client import langfuse
except Exception:  # pragma: no cover
    langfuse = None


class _NoopSpan:
    trace_id = None
    id = None

    def start_observation(self, **kwargs):
        return _NoopSpan()

    def update(self, **kwargs):
        return self

    def end(self):
        pass


class InvestigationTracer:
    """Wraps a Langfuse trace around one investigation. Never raises."""

    def __init__(self, question: str):
        self._root = None
        self._spans: dict[str, Any] = {}
        self._timings: dict[str, float] = {}
        if langfuse is None:
            return
        try:
            self._root = langfuse.start_observation(
                name="investigation",
                as_type="chain",
                metadata={"question_length": len(question)},
            )
        except Exception:
            logger.warning("Langfuse trace start failed (non-fatal)", exc_info=True)
            self._root = None

    @property
    def trace_id(self) -> str | None:
        return getattr(self._root, "trace_id", None)

    def start_stage(self, stage: str, metadata: dict | None = None):
        self._timings[stage] = time.monotonic()
        if self._root is None:
            return _NoopSpan()
        try:
            span = self._root.start_observation(name=stage, as_type="span", metadata=metadata or {})
            self._spans[stage] = span
            return span
        except Exception:
            logger.warning("Langfuse span '%s' failed (non-fatal)", stage)
            return _NoopSpan()

    def end_stage(self, stage: str, metadata: dict | None = None):
        started = self._timings.pop(stage, None)
        duration_ms = (time.monotonic() - started) * 1000 if started else None
        # Stage timing is also logged so latency is observable without Langfuse.
        if duration_ms is not None:
            logger.info("Stage '%s' completed in %.0f ms", stage, duration_ms)
        span = self._spans.pop(stage, None)
        if span is None:
            return
        try:
            if metadata:
                span.update(metadata=metadata)
            span.end()
        except Exception:
            logger.warning("Langfuse span '%s' close failed (non-fatal)", stage)

    def end(self, metadata: dict | None = None):
        # Close any stage left open by an exception path.
        for stage in list(self._spans):
            self.end_stage(stage)
        try:
            if self._root is not None:
                if metadata:
                    self._root.update(metadata=metadata)
                self._root.end()
            if langfuse is not None:
                langfuse.flush()
        except Exception:
            logger.warning("Langfuse trace close failed (non-fatal)")
