"""Cooperative cancellation for investigations.

When the client disconnects, the API sets the request's ``CancellationToken``.
The workflow then stops at the next check:
  * before every workflow stage (rca_graph wraps each node);
  * before every LLM attempt (llm_client.call_with_retry);
  * during retry backoff sleeps (the sleep wakes up immediately).
An LLM HTTP request already in flight is not interrupted; its result is
discarded at the next check.

``InvestigationCancelled`` derives from BaseException (like
asyncio.CancelledError) so the fail-soft ``except Exception`` handlers in the
agents cannot swallow a cancellation and turn it into a fallback answer.
"""

import contextvars
import threading
import time


class InvestigationCancelled(BaseException):
    def __init__(self, stage: str, reason: str | None = None):
        super().__init__(f"investigation cancelled at {stage}" + (f" ({reason})" if reason else ""))
        self.stage = stage
        self.reason = reason


class CancellationToken:
    def __init__(self):
        self._event = threading.Event()
        self.reason: str | None = None

    def cancel(self, reason: str = "client disconnected") -> None:
        self.reason = reason
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self, stage: str) -> None:
        if self._event.is_set():
            raise InvestigationCancelled(stage, self.reason)

    def sleep(self, seconds: float, stage: str) -> None:
        """Sleep, waking immediately (and raising) if cancelled meanwhile."""
        if self._event.wait(max(0.0, seconds)):
            raise InvestigationCancelled(stage, self.reason)


_current: contextvars.ContextVar[CancellationToken | None] = contextvars.ContextVar("cancellation_token",
                                                                                   default=None)


def bind(token: CancellationToken | None):
    """Make ``token`` visible to code running in this context (e.g. the LLM layer)."""
    return _current.set(token)


def unbind(reset_token) -> None:
    _current.reset(reset_token)


def check(stage: str) -> None:
    token = _current.get()
    if token is not None:
        token.raise_if_cancelled(stage)


def cancellable_sleep(seconds: float) -> None:
    token = _current.get()
    if token is None:
        time.sleep(seconds)
    else:
        token.sleep(seconds, "llm_backoff")
