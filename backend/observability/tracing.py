"""Langfuse tracing for investigations - one trace per investigation with
meaningful stage spans. Fail-soft: if Langfuse is unavailable, tracing
calls become no-ops and the investigation continues."""

import logging
import time

logger = logging.getLogger(__name__)

try:
    from observability.langfuse_client import langfuse
except Exception:  # pragma: no cover
    langfuse = None


class _NoopSpan:
    def event(self, name=None, metadata=None):
        pass

    def end(self):
        pass


class _NoopTrace:
    def start_span(self, name=None, metadata=None):
        return _NoopSpan()

    def end(self):
        pass


class InvestigationTracer:
    """Wraps a Langfuse trace around one investigation. Never raises."""

    def __init__(self, question: str):
        self._trace = None
        self._timings: dict[str, float] = {}
        if langfuse is None:
            return
        try:
            self._trace = langfuse.start_trace(
                name="investigation",
                metadata={
                    "question_length": len(question),
                    # Only question length is recorded - not the question
                    # itself - to avoid storing sensitive enterprise data.
                },
            )
        except Exception:
            logger.warning("Langfuse trace start failed (non-fatal)")
            self._trace = None

    def start_stage(self, stage: str, metadata: dict | None = None):
        self._timings[stage] = time.monotonic()
        if self._trace is None:
            return _NoopSpan()
        try:
            return self._trace.start_span(name=stage, metadata=metadata or {})
        except Exception:
            logger.warning("Langfuse span '%s' failed (non-fatal)", stage)
            return _NoopSpan()

    def end_stage(self, stage: str, metadata: dict | None = None):
        started = self._timings.pop(stage, None)
        duration_ms = (time.monotonic() - started) * 1000 if started else None
        # Stage timing is also logged so latency is observable without Langfuse.
        if duration_ms is not None:
            logger.info("Stage '%s' completed in %.0f ms", stage, duration_ms)
        # Spans are ended by their owners; nothing else to do here.

    def end(self, metadata: dict | None = None):
        try:
            if self._trace is not None:
                if metadata:
                    try:
                        self._trace.update(metadata=metadata)
                    except Exception:
                        pass
                self._trace.end()
            if langfuse is not None:
                langfuse.flush()
        except Exception:
            logger.warning("Langfuse trace close failed (non-fatal)")
