"""Central application configuration.

All environment-driven settings live here so the rest of the codebase never
reads os.environ directly and secrets never leak into logs or responses.
"""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

# Paths are resolved relative to this file so the app works no matter where
# uvicorn is launched from.
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
RUNBOOKS_DIR = DATA_DIR / "runbooks"

load_dotenv(BASE_DIR / ".env")
load_dotenv(BASE_DIR.parent / ".env")  # also support repo-root .env


def _get_csv(name: str, default: str) -> list[str]:
    raw = os.getenv(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


class Settings:
    # --- Gemini ---
    GEMINI_API_KEY: str | None = os.getenv("GEMINI_API_KEY")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    GEMINI_TIMEOUT_MS: int = int(os.getenv("GEMINI_TIMEOUT_MS", "60000"))
    GEMINI_MAX_RETRIES: int = int(os.getenv("GEMINI_MAX_RETRIES", "2"))

    # --- Langfuse ---
    LANGFUSE_PUBLIC_KEY: str | None = os.getenv("LANGFUSE_PUBLIC_KEY")
    LANGFUSE_SECRET_KEY: str | None = os.getenv("LANGFUSE_SECRET_KEY")
    LANGFUSE_HOST: str | None = os.getenv("LANGFUSE_HOST")

    # --- Qdrant ---
    QDRANT_PATH: str = os.getenv(
        "QDRANT_PATH", str(BASE_DIR / "qdrant_data")
    )
    QDRANT_COLLECTION: str = os.getenv("QDRANT_COLLECTION", "enterprise_incidents")

    # --- API / CORS ---
    CORS_ORIGINS: list[str] = _get_csv(
        "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    )
    # Simple per-IP rate limit for the expensive /investigate endpoint.
    INVESTIGATE_RATE_LIMIT: int = int(os.getenv("INVESTIGATE_RATE_LIMIT", "10"))
    INVESTIGATE_RATE_WINDOW_SECONDS: int = int(
        os.getenv("INVESTIGATE_RATE_WINDOW_SECONDS", "60")
    )

    # --- Validation limits (mirrored on the frontend) ---
    QUESTION_MIN_LENGTH: int = int(os.getenv("QUESTION_MIN_LENGTH", "8"))
    QUESTION_MAX_LENGTH: int = int(os.getenv("QUESTION_MAX_LENGTH", "500"))

    # --- Retrieval quality ---
    MIN_RELEVANCE_SCORE: float = float(os.getenv("MIN_RELEVANCE_SCORE", "0.30"))

    # --- Logging ---
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")


settings = Settings()


def configure_logging() -> None:
    """Configure root logging once; called by app startup and tests."""
    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )
    # Keep third-party noise down.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


configure_logging()

if not settings.GEMINI_API_KEY:
    logging.getLogger(__name__).warning(
        "GEMINI_API_KEY is not set - RCA generation will fall back to "
        "an evidence-only report until the key is configured."
    )
