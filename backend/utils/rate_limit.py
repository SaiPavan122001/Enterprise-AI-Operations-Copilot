import logging
import time

from fastapi import Request

from config import settings

logger = logging.getLogger(__name__)


class RateLimiter:
    """Small in-memory sliding-window rate limiter.

    Protects the expensive LLM-backed /investigate endpoints from
    unrestricted API spend. Requests are counted per authenticated identity
    (API-key name) when known, otherwise per client IP.

    LIMITATION: state is in this process's memory. With several worker
    processes or replicas each keeps its own counts (the effective limit
    multiplies) and counts reset on restart. A multi-process deployment needs a
    shared store (e.g. Redis) - see evals/RELIABILITY_AUDIT.md (D16).
    """

    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict[str, list[float]] = {}

    def check(self, request: Request, identity: str | None = None) -> bool:
        client_ip = (f"key:{identity}" if identity
                     else request.client.host if request.client else "unknown")
        now = time.monotonic()
        window_start = now - self.window_seconds

        hits = [t for t in self._hits.get(client_ip, []) if t > window_start]
        if len(hits) >= self.max_requests:
            self._hits[client_ip] = hits
            logger.warning("Rate limit exceeded for client %s", client_ip)
            return False

        hits.append(now)
        self._hits[client_ip] = hits
        return True


investigate_limiter = RateLimiter(
    settings.INVESTIGATE_RATE_LIMIT,
    settings.INVESTIGATE_RATE_WINDOW_SECONDS,
)
