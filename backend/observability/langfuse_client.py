"""Langfuse client - initialised defensively.

Langfuse is optional observability: if keys are missing or the service is
unreachable, the RCA pipeline must keep working. Consumers must tolerate
``langfuse`` being ``None``.
"""

import logging
import os

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()

langfuse = None
try:
    from langfuse import Langfuse

    langfuse = Langfuse(
        public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
        secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
        host=os.getenv("LANGFUSE_HOST"),
    )
    logger.info("Langfuse initialised")
except Exception as exc:  # pragma: no cover - depends on environment
    logger.warning("Langfuse not available (observability disabled): %s", type(exc).__name__)
    langfuse = None
