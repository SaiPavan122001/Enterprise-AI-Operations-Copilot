"""Provider-neutral retry, backoff and error classification for LLM calls.

Errors are classified so each kind is handled correctly:

* ``LLMTransientError``   - 5xx / overloaded / timeouts / connection errors:
  retried with exponential backoff + full jitter.
* ``LLMRateLimitError``   - per-minute rate limits: retried, waiting at least
  the provider's suggested delay.
* ``LLMQuotaExhaustedError`` - billing/daily quota exhausted: never retried,
  and further calls to that provider are skipped for a cooldown period so a
  batch of requests doesn't hammer an exhausted quota.
* ``LLMConfigError``      - bad/missing key, unknown model, permission or bad
  request: never retried; fails clearly.
* ``LLMError``            - anything unrecognised: not retried.

The provider SDK's own retries must be disabled so they don't stack with ours.
"""

import logging
import random
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

logger = logging.getLogger(__name__)


class LLMError(Exception):
    kind = "error"
    retryable = False

    def __init__(self, message: str, *, provider: str, retry_after: float | None = None):
        super().__init__(message)
        self.provider = provider
        self.retry_after = retry_after


class LLMTransientError(LLMError):
    kind = "transient"
    retryable = True


class LLMRateLimitError(LLMError):
    kind = "rate_limit"
    retryable = True


class LLMQuotaExhaustedError(LLMError):
    kind = "quota_exhausted"


class LLMConfigError(LLMError):
    kind = "config"


@dataclass
class LLMResponse:
    text: str
    provider: str
    model: str
    usage: dict = field(default_factory=dict)   # {"input": int, "output": int}
    attempts: int = 1


# --------------------------------------------------------------------------- quota breaker

_quota_lock = threading.Lock()
_quota_blocked_until: dict[str, float] = {}


def quota_blocked(provider: str) -> bool:
    with _quota_lock:
        return time.monotonic() < _quota_blocked_until.get(provider, 0.0)


def block_quota(provider: str, seconds: float) -> None:
    with _quota_lock:
        _quota_blocked_until[provider] = time.monotonic() + seconds


def reset_quota_block(provider: str | None = None) -> None:
    with _quota_lock:
        if provider is None:
            _quota_blocked_until.clear()
        else:
            _quota_blocked_until.pop(provider, None)


# --------------------------------------------------------------------------- classification

_RETRY_DELAY_RE = re.compile(r"retry in ([\d.]+)s", re.IGNORECASE)


def _gemini_retry_delay(details) -> float | None:
    """Parse google.rpc.RetryInfo ('82002s') from a Gemini error body."""
    try:
        for d in details.get("error", {}).get("details", []):
            if d.get("@type", "").endswith("RetryInfo") and d.get("retryDelay"):
                return float(str(d["retryDelay"]).rstrip("s"))
    except (AttributeError, ValueError, TypeError):
        pass
    return None


def _gemini_quota_ids(details) -> list[str]:
    """quotaId values from google.rpc.QuotaFailure, e.g.
    'GenerateRequestsPerDayPerProjectPerModel-FreeTier' or '...PerMinute...'."""
    ids: list[str] = []
    try:
        for d in details.get("error", {}).get("details", []):
            if d.get("@type", "").endswith("QuotaFailure"):
                ids += [v.get("quotaId", "") for v in d.get("violations", [])]
    except (AttributeError, TypeError):
        pass
    return [i for i in ids if i]


def classify_gemini(exc: Exception) -> LLMError:
    from google.genai import errors as genai_errors

    msg = str(exc)[:500]
    if isinstance(exc, genai_errors.APIError):
        code = getattr(exc, "code", None)
        details = getattr(exc, "details", None) or {}
        if code == 429:
            delay = _gemini_retry_delay(details)
            quota_ids = _gemini_quota_ids(details)
            # 1) quotaId is authoritative: a per-day quota can't be fixed by
            #    retrying; per-minute/per-second limits can.
            if any("PerDay" in q for q in quota_ids):
                return LLMQuotaExhaustedError(msg, provider="gemini", retry_after=delay)
            if quota_ids:
                return LLMRateLimitError(msg, provider="gemini", retry_after=delay)
            # 2) No quotaId: a very long suggested wait means a quota stop.
            if delay is not None:
                if delay > 3600:
                    return LLMQuotaExhaustedError(msg, provider="gemini", retry_after=delay)
                return LLMRateLimitError(msg, provider="gemini", retry_after=delay)
            # 3) Last resort: message text (both kinds may mention billing, so
            #    only an explicit per-day/daily wording counts as quota).
            text = str(details).lower()
            if "per day" in text or "perday" in text or "daily" in text:
                return LLMQuotaExhaustedError(msg, provider="gemini")
            return LLMRateLimitError(msg, provider="gemini")
        if code in (400, 401, 403, 404):
            return LLMConfigError(msg, provider="gemini")
        if code is not None and code >= 500:
            return LLMTransientError(msg, provider="gemini")
    if _is_network_error(exc):
        return LLMTransientError(msg, provider="gemini")
    return LLMError(msg, provider="gemini")


def classify_openai(exc: Exception) -> LLMError:
    import openai

    msg = str(exc)[:500]
    if isinstance(exc, openai.RateLimitError):
        body = getattr(exc, "body", None) or {}
        code = (body.get("code") if isinstance(body, dict) else None) or ""
        etype = (body.get("type") if isinstance(body, dict) else None) or ""
        if "insufficient_quota" in (code, etype) or "credit_balance" in code:
            return LLMQuotaExhaustedError(msg, provider="openai")
        retry_after = None
        try:
            header = exc.response.headers.get("retry-after")
            retry_after = float(header) if header else None
        except (AttributeError, ValueError):
            pass
        if retry_after is None:
            m = _RETRY_DELAY_RE.search(msg)
            retry_after = float(m.group(1)) if m else None
        return LLMRateLimitError(msg, provider="openai", retry_after=retry_after)
    if isinstance(exc, (openai.AuthenticationError, openai.PermissionDeniedError,
                        openai.NotFoundError, openai.BadRequestError)):
        return LLMConfigError(msg, provider="openai")
    if isinstance(exc, (openai.APITimeoutError, openai.APIConnectionError,
                        openai.InternalServerError)):
        return LLMTransientError(msg, provider="openai")
    if isinstance(exc, openai.APIStatusError) and exc.status_code >= 500:
        return LLMTransientError(msg, provider="openai")
    if _is_network_error(exc):
        return LLMTransientError(msg, provider="openai")
    return LLMError(msg, provider="openai")


def _is_network_error(exc: Exception) -> bool:
    """Timeouts / connection failures from httpx (openai SDK), requests
    (google-genai 0.6 SDK) or the standard library."""
    try:
        import httpx

        if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError)):
            return True
    except ImportError:  # pragma: no cover
        pass
    try:
        import requests

        if isinstance(exc, (requests.exceptions.Timeout, requests.exceptions.ConnectionError)):
            return True
    except ImportError:  # pragma: no cover
        pass
    return isinstance(exc, (TimeoutError, ConnectionError))


CLASSIFIERS: dict[str, Callable[[Exception], LLMError]] = {
    "gemini": classify_gemini,
    "openai": classify_openai,
}


# --------------------------------------------------------------------------- retry loop

def backoff_delay(attempt: int, base: float, cap: float, retry_after: float | None = None,
                  rng: Callable[[float, float], float] = random.uniform) -> float:
    """Full-jitter exponential backoff; never shorter than the provider's hint."""
    delay = rng(0.0, min(cap, base * (2 ** (attempt - 1))))
    if retry_after is not None:
        delay = max(delay, retry_after)
    return delay


def call_with_retry(call: Callable[[], LLMResponse], *, provider: str, max_retries: int,
                    base: float, cap: float, quota_cooldown: float,
                    sleep: Callable[[float], None] | None = None) -> LLMResponse:
    from utils import cancellation

    # Backoff sleeps wake up (and raise) as soon as the investigation is cancelled.
    sleep = sleep or cancellation.cancellable_sleep
    if quota_blocked(provider):
        raise LLMQuotaExhaustedError(
            f"{provider} quota was reported exhausted recently; not calling again until cooldown ends",
            provider=provider)
    classify = CLASSIFIERS[provider]
    attempts = max(0, max_retries) + 1
    for attempt in range(1, attempts + 1):
        cancellation.check("llm_call")       # never start an attempt for a cancelled request
        try:
            response = call()
            response.attempts = attempt
            return response
        except LLMError:
            raise
        except Exception as exc:
            err = classify(exc)
            if isinstance(err, LLMQuotaExhaustedError):
                block_quota(provider, quota_cooldown)
            if not err.retryable or attempt == attempts:
                logger.error("%s call failed (%s, attempt %d/%d): %s",
                             provider, err.kind, attempt, attempts, err)
                raise err from exc
            # A suggested wait far beyond our cap is effectively a quota stop.
            if err.retry_after is not None and err.retry_after > cap * 4:
                block_quota(provider, quota_cooldown)
                raise LLMQuotaExhaustedError(
                    f"{provider} asked to wait {err.retry_after:.0f}s: {err}",
                    provider=provider, retry_after=err.retry_after) from exc
            delay = backoff_delay(attempt, base, cap, err.retry_after)
            logger.warning("%s call failed (%s, attempt %d/%d) - retrying in %.1fs",
                           provider, err.kind, attempt, attempts, delay)
            sleep(delay)
    raise LLMError("unreachable", provider=provider)  # pragma: no cover
