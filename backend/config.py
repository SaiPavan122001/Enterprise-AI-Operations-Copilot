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
    # --- RCA answer generation (provider is switchable by configuration) ---
    # "gemini" or "openai". Each provider keeps its own key/model/timeout/retries.
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "gemini").strip().lower()
    # Exponential backoff with full jitter for retryable failures (5xx,
    # timeouts, per-minute rate limits). Quota exhaustion is never retried.
    LLM_BACKOFF_BASE_SECONDS: float = float(os.getenv("LLM_BACKOFF_BASE_SECONDS", "1.0"))
    LLM_BACKOFF_MAX_SECONDS: float = float(os.getenv("LLM_BACKOFF_MAX_SECONDS", "30"))
    # After a quota-exhausted response, skip calls to that provider for this long.
    LLM_QUOTA_COOLDOWN_SECONDS: float = float(os.getenv("LLM_QUOTA_COOLDOWN_SECONDS", "900"))

    # --- Gemini ---
    GEMINI_API_KEY: str | None = os.getenv("GEMINI_API_KEY")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    GEMINI_TIMEOUT_MS: int = int(os.getenv("GEMINI_TIMEOUT_MS", "60000"))
    GEMINI_MAX_RETRIES: int = int(os.getenv("GEMINI_MAX_RETRIES", "2"))

    # --- OpenAI ---
    OPENAI_API_KEY: str | None = os.getenv("OPENAI_API_KEY")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    OPENAI_TIMEOUT_MS: int = int(os.getenv("OPENAI_TIMEOUT_MS", "60000"))
    OPENAI_MAX_RETRIES: int = int(os.getenv("OPENAI_MAX_RETRIES", "2"))

    @property
    def llm_model(self) -> str:
        return self.OPENAI_MODEL if self.LLM_PROVIDER == "openai" else self.GEMINI_MODEL

    @property
    def llm_api_key(self) -> str | None:
        return self.OPENAI_API_KEY if self.LLM_PROVIDER == "openai" else self.GEMINI_API_KEY

    @property
    def llm_max_retries(self) -> int:
        return self.OPENAI_MAX_RETRIES if self.LLM_PROVIDER == "openai" else self.GEMINI_MAX_RETRIES

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
    # Scores are Qdrant cosine similarities (higher = more similar) from
    # BAAI/bge-small-en-v1.5, whose scores are compressed: unrelated text
    # typically scores 0.55-0.80. Calibrated with evals/calibrate_retrieval.py
    # (dev/held-out split of evals/testsets/testset_v1.jsonl):
    #   floor 0.60 + margin 0.10 keeps 100% of expected incidents (incl.
    #   multi-incident questions) while raising precision from ~0.24 to ~0.70.
    # An incident is passed to the LLM only if score >= MIN_RELEVANCE_SCORE
    # AND score >= (best score - RELEVANCE_MARGIN).
    MIN_RELEVANCE_SCORE: float = float(os.getenv("MIN_RELEVANCE_SCORE", "0.60"))
    RELEVANCE_MARGIN: float = float(os.getenv("RELEVANCE_MARGIN", "0.10"))
    # Best-incident score required for HIGH evidence strength.
    STRONG_RELEVANCE_SCORE: float = float(os.getenv("STRONG_RELEVANCE_SCORE", "0.75"))

    # --- Authentication (utils/auth.py) ---
    # api_key (default, fail-closed) | disabled (explicit, local development only)
    AUTH_MODE: str = os.getenv("AUTH_MODE", "api_key").strip().lower()
    # Comma-separated name:role:sha256hex entries (roles: viewer, investigator, admin).
    API_KEYS: str | None = os.getenv("API_KEYS")

    # --- Browser sessions, users, resource access (security/) ---
    # Users (scrypt password hashes, role, tenant, service grants); managed with
    # `python -m security.users`. Kept under backend/storage/ (git-ignored).
    USERS_FILE: str = os.getenv("USERS_FILE", str(BASE_DIR / "storage" / "users.json"))
    ACCESS_POLICY_FILE: str | None = os.getenv("ACCESS_POLICY_FILE") or None
    SESSION_TTL_MINUTES: int = int(os.getenv("SESSION_TTL_MINUTES", "480"))
    SESSION_IDLE_MINUTES: int = int(os.getenv("SESSION_IDLE_MINUTES", "60"))
    # Secure cookies by default; browsers accept them on http://localhost.
    SESSION_COOKIE_SECURE: bool = os.getenv("SESSION_COOKIE_SECURE", "true").strip().lower() != "false"
    LOGIN_MAX_FAILURES: int = int(os.getenv("LOGIN_MAX_FAILURES", "5"))
    LOGIN_LOCKOUT_MINUTES: int = int(os.getenv("LOGIN_LOCKOUT_MINUTES", "15"))
    AUDIT_DIR: str = os.getenv("AUDIT_DIR", str(BASE_DIR / "storage" / "audit"))

    # --- PII protection (security/pii.py) ---
    # presidio (default) | regex (no NLP model) | off
    PII_ENGINE: str = os.getenv("PII_ENGINE", "presidio").strip().lower()
    PII_SPACY_MODEL: str = os.getenv("PII_SPACY_MODEL", "en_core_web_sm")

    # --- NeMo Guardrails (security/guardrails/) ---
    # nemo (default) | off. Only 'off' disables the rails; any other value keeps them on (logged).
    # The deterministic actions run even if NeMo itself fails.
    GUARDRAILS_MODE: str = os.getenv("GUARDRAILS_MODE", "nemo").strip().lower()
    # Extra LLM self-check on the input rail, through the project's LLM provider.
    GUARDRAILS_LLM_SELF_CHECK: bool = os.getenv("GUARDRAILS_LLM_SELF_CHECK", "true").strip().lower() != "false"
    # Wall-clock limit per rail call; an input rail that overruns declines the request.
    GUARDRAILS_TIMEOUT_SECONDS: float = float(os.getenv("GUARDRAILS_TIMEOUT_SECONDS", "30"))

    # --- Tools and approvals (tools/, approvals/) ---
    # Only "simulated" is implemented; any other value refuses consequential actions.
    REMEDIATION_MODE: str = os.getenv("REMEDIATION_MODE", "simulated").strip().lower()
    APPROVAL_PENDING_TTL_MINUTES: int = int(os.getenv("APPROVAL_PENDING_TTL_MINUTES", "60"))
    APPROVAL_VALID_MINUTES: int = int(os.getenv("APPROVAL_VALID_MINUTES", "15"))
    APPROVALS_FILE: str = os.getenv("APPROVALS_FILE", str(BASE_DIR / "storage" / "approvals.json"))

    # --- Claim-support verifier (agents/claim_verifier.py) ---
    # "nli": deterministic checks + a local NLI cross-encoder; "deterministic": no model;
    # "off": neither. The NLI model is fallible - see evals/claim_verifier_eval.py.
    CLAIM_VERIFIER: str = os.getenv("CLAIM_VERIFIER", "nli").strip().lower()
    CLAIM_VERIFIER_MODEL: str = os.getenv("CLAIM_VERIFIER_MODEL", "cross-encoder/nli-deberta-v3-xsmall")
    # Pinned Hugging Face revision (the snapshot the verifier was measured with).
    CLAIM_VERIFIER_MODEL_REVISION: str = os.getenv("CLAIM_VERIFIER_MODEL_REVISION",
                                                   "a150876415327c80daeff35ca6f68f5ed8cf5c24")

    # --- Logging ---
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_FORMAT: str = os.getenv("LOG_FORMAT", "text").strip().lower()   # text | json


settings = Settings()


def configure_logging() -> None:
    """Configure root logging once; called by app startup and tests."""
    from utils.log_context import install

    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    # Text by default; LOG_FORMAT=json for one structured object per line.
    # Both carry request/investigation IDs and redact credentials (utils/log_context.py).
    install(level, settings.LOG_FORMAT)
    # Keep third-party noise down.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


configure_logging()

if settings.LLM_PROVIDER not in ("gemini", "openai"):
    logging.getLogger(__name__).error(
        "LLM_PROVIDER=%r is not supported (use 'gemini' or 'openai') - RCA "
        "generation will fail and return evidence-only reports.", settings.LLM_PROVIDER,
    )
elif not settings.llm_api_key:
    logging.getLogger(__name__).warning(
        "%s_API_KEY is not set (LLM_PROVIDER=%s) - RCA generation will fall back "
        "to an evidence-only report until the key is configured.",
        settings.LLM_PROVIDER.upper(), settings.LLM_PROVIDER,
    )
