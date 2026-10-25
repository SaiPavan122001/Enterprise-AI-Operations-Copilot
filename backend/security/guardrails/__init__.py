"""NVIDIA NeMo Guardrails around the investigation pipeline.

Three rail configurations (``config/input``, ``config/retrieval``,
``config/output``) orchestrate deterministic checks (``checks.py``) and one
model-based self-check that goes through the project's own LLM provider. NeMo's
own LLM slot is a stub that is never called (asserted in tests), so provider
switching, retries, caching and cancellation stay in one place.

* input rails     - on the (PII-redacted) question: prompt injection, action
                    requests, requests for secrets / personal data, LLM self-check.
* retrieval rails - on every retrieved record field: instruction-like sentences
                    are neutralised before any prompt sees them.
* output rails    - on the validated answer: unsafe advice / links / commands /
                    credential requests / exfiltration instructions / repeated
                    internal instructions removed.

They COMPLEMENT the existing controls (citation validation, claim verification,
causal guards, confidence caps, safe failure); none of those is bypassed.

``GUARDRAILS_MODE=nemo`` (default) | ``off``. Only the exact value ``off``
disables the rails; any other value keeps them on (and is logged).

Failure handling:
* NeMo catches exceptions raised inside actions and answers "internal error"
  with the rail variables unset. Every action is therefore wrapped: its exception
  is recorded and re-raised after NeMo returns, so a crashed check is never read
  as "passed" (and a cancellation is never lost).
* If NeMo fails, the same checks run directly (``engine="direct"``).
* The input rail FAILS CLOSED: if its checks cannot complete (crash, timeout,
  unusable self-check answer) the request is declined (``guardrail_unavailable``).
* Retrieval and output rails fall back to the deterministic checks, which need
  no model.
* Every rail call has a wall-clock limit (``GUARDRAILS_TIMEOUT_SECONDS``).
"""

import asyncio
import concurrent.futures
import contextvars
import functools
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from config import settings
from security.guardrails import checks

logger = logging.getLogger(__name__)
CONFIG_DIR = Path(__file__).with_name("config")
BLOCKED = "GUARDRAIL_BLOCKED"
UNAVAILABLE = checks.UNAVAILABLE
_NEMO_INTERNAL_ERROR = "I'm sorry, an internal error has occurred"


@dataclass
class InputVerdict:
    blocked: bool = False
    reason: str = ""
    engine: str = "off"            # nemo | direct | off
    latency_ms: float = 0.0
    rails: list[str] = field(default_factory=list)

    @property
    def category(self) -> str:
        return self.reason.split(":", 1)[0] if self.reason else ""


class GuardrailTimeout(Exception):
    pass


def _cancelled(exc: BaseException) -> bool:
    return type(exc).__name__ == "InvestigationCancelled"


_warned_modes: set[str] = set()


def enabled() -> bool:
    mode = settings.GUARDRAILS_MODE
    if mode == "off":
        return False
    if mode != "nemo" and mode not in _warned_modes:
        _warned_modes.add(mode)
        logger.error("GUARDRAILS_MODE=%r is not 'nemo' or 'off' - guardrails stay ON", mode)
    return True


# --------------------------------------------------------------------------- NeMo actions

async def _a_injection(text: str):
    return checks.input_injection(text)


async def _a_policy(text: str):
    return checks.input_policy(text)


async def _a_self_check(text: str):
    if not settings.GUARDRAILS_LLM_SELF_CHECK:
        return ""
    return await asyncio.to_thread(checks.llm_self_check, text)


async def _a_neutralize(text: str):
    items = json.loads(text)
    return json.dumps([checks.neutralize_record_text(t)[0] for t in items])


async def _a_output(text: str, evidence: str, links: str):
    sections, removed = checks.sanitize_sections(json.loads(text), evidence or "", links or "")
    return json.dumps({"sections": sections, "removed": removed})


_rails: dict[str, object] = {}
_locks = {k: threading.Lock() for k in ("input", "retrieval", "output")}
_init_lock = threading.Lock()
_nemo_error: str | None = None
_action_errors: dict[str, BaseException] = {}
_executor = concurrent.futures.ThreadPoolExecutor(max_workers=8, thread_name_prefix="guardrails")


def _recording(kind: str, fn):
    """NeMo swallows action exceptions; keep the first one so _run can re-raise it."""
    @functools.wraps(fn)
    async def action(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except BaseException as exc:
            _action_errors.setdefault(kind, exc)
            raise
    return action


def _get(kind: str):
    global _nemo_error
    with _init_lock:
        if kind not in _rails and _nemo_error is None:
            try:
                logging.getLogger("nemoguardrails").setLevel(logging.WARNING)
                from langchain_core.language_models.fake import FakeListLLM
                from nemoguardrails import LLMRails, RailsConfig

                # Stub LLM: rails here only run actions; a call would return this marker.
                stub = FakeListLLM(responses=["NEMO_STUB_LLM_MUST_NOT_BE_CALLED"])
                rails = LLMRails(RailsConfig.from_path(str(CONFIG_DIR / kind)), llm=stub)
                for name, fn in (("input_injection_check", _a_injection), ("input_policy_check", _a_policy),
                                 ("input_llm_self_check", _a_self_check), ("retrieval_neutralize", _a_neutralize),
                                 ("output_sanitize", _a_output)):
                    rails.register_action(_recording(kind, fn), name)
                _rails[kind] = rails
            except Exception as exc:
                _nemo_error = type(exc).__name__
                logger.error("NeMo Guardrails unavailable (%s) - running the same checks directly", _nemo_error)
    return _rails.get(kind)


def _run_locked(kind: str, rails, messages: list[dict], options: dict, deadline: float):
    if not _locks[kind].acquire(timeout=max(0.0, deadline - time.monotonic())):
        raise GuardrailTimeout(f"{kind} rail timed out waiting for a worker")
    try:
        _action_errors.pop(kind, None)
        res = asyncio.run(rails.generate_async(messages=messages, options=options))
        err = _action_errors.pop(kind, None)
        if err is not None:
            raise err
        if res is not None and res.response and str(res.response[0].get("content", "")).startswith(
                _NEMO_INTERNAL_ERROR):
            raise RuntimeError(f"NeMo {kind} rail reported an internal error")
        return res
    finally:
        _locks[kind].release()


def _run(kind: str, messages: list[dict], options: dict):
    """One NeMo rail call with a wall-clock limit. A call that overruns keeps its
    worker thread until it finishes, but the request no longer waits for it."""
    rails = _get(kind)
    if rails is None:
        return None
    limit = settings.GUARDRAILS_TIMEOUT_SECONDS
    deadline = time.monotonic() + limit
    future = _executor.submit(contextvars.copy_context().run, _run_locked, kind, rails, messages, options,
                              deadline)
    try:
        return future.result(timeout=limit)
    except concurrent.futures.TimeoutError:
        raise GuardrailTimeout(f"{kind} rail timed out after {limit:g}s") from None


def status() -> str:
    if not enabled():
        return "off"
    _get("input")
    return "nemo" if _nemo_error is None else f"direct (nemo unavailable: {_nemo_error})"


# --------------------------------------------------------------------------- public API

def check_input(text: str) -> InputVerdict:
    """Input rail. Fails closed: if the checks cannot complete, the request is declined."""
    if not enabled():
        return InputVerdict()
    start = time.perf_counter()

    def ms() -> float:
        return (time.perf_counter() - start) * 1000

    try:
        res = _run("input", [{"role": "user", "content": text}],
                   {"rails": ["input"], "output_vars": ["guardrail_block"], "log": {"activated_rails": True}})
    except GuardrailTimeout as exc:
        logger.error("Input rail: %s - request declined", exc)
        return InputVerdict(blocked=True, reason=f"{UNAVAILABLE}: {exc}", engine="nemo", latency_ms=ms())
    except Exception as exc:
        if _cancelled(exc):
            raise
        logger.error("NeMo input rail failed (%s) - running checks directly", type(exc).__name__)
        res = None
    if res is not None:
        reason = (res.output_data or {}).get("guardrail_block") or ""
        blocked = bool(reason) or (res.response and res.response[0].get("content") == BLOCKED)
        return InputVerdict(blocked=bool(blocked), reason=reason or ("blocked" if blocked else ""), engine="nemo",
                            latency_ms=ms(), rails=[a.name for a in (res.log.activated_rails if res.log else [])])
    try:
        reason = checks.input_injection(text) or checks.input_policy(text) or \
            (checks.llm_self_check(text) if settings.GUARDRAILS_LLM_SELF_CHECK else "")
    except Exception as exc:
        if _cancelled(exc):
            raise
        logger.error("Input checks failed (%s) - request declined", type(exc).__name__)
        reason = f"{UNAVAILABLE}: input checks failed ({type(exc).__name__})"
    return InputVerdict(blocked=bool(reason), reason=reason, engine="direct", latency_ms=ms())


def neutralize_with_engine(texts: list[str]) -> tuple[list[str], int, str]:
    """Retrieval rail over record texts; returns (texts, number changed, engine)."""
    if not enabled() or not texts:
        return texts, 0, "off"
    out, engine = None, "nemo"
    try:
        res = _run("retrieval", [{"role": "user", "content": json.dumps(texts)}],
                   {"rails": ["input"], "output_vars": ["user_message"]})
        if res is not None:
            out = json.loads((res.output_data or {}).get("user_message") or "null")
    except Exception as exc:
        if _cancelled(exc):
            raise
        logger.error("NeMo retrieval rail failed (%s) - running checks directly", type(exc).__name__)
    if not isinstance(out, list) or len(out) != len(texts):
        out, engine = [checks.neutralize_record_text(t)[0] for t in texts], "direct"
    return out, sum(1 for a, b in zip(texts, out) if a != b), engine


def neutralize(texts: list[str]) -> tuple[list[str], int]:
    """Retrieval rail over record texts; returns (texts, number changed)."""
    out, changed, _ = neutralize_with_engine(texts)
    return out, changed


def sanitize_output(sections: dict, evidence: str, links_from: str | None = None) -> tuple[dict, list[str]]:
    """Output rail; returns (sections, removal notes). Links / e-mail addresses are
    allowed only from ``links_from`` (default: the evidence). A fallback to the
    direct checks is reported as a note."""
    if not enabled():
        return sections, []
    links_from = evidence if links_from is None else links_from
    try:
        res = _run("output", [{"role": "context", "content": {"evidence_text": evidence, "link_text": links_from}},
                              {"role": "user", "content": "answer"},
                              {"role": "assistant", "content": json.dumps(sections, default=str)}],
                   {"rails": ["output"]})
        if res is not None:
            data = json.loads(res.response[0]["content"])
            return data["sections"], data["removed"]
    except Exception as exc:
        if _cancelled(exc):
            raise
        logger.error("NeMo output rail failed (%s) - running checks directly", type(exc).__name__)
    out, removed = checks.sanitize_sections(sections, evidence, links_from)
    return out, ["ran the checks directly (NeMo output rail unavailable)"] + removed
