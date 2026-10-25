import logging
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]

# Make the backend package importable regardless of where pytest is invoked.
sys.path.insert(0, str(BACKEND_DIR))

logging.getLogger().setLevel(logging.WARNING)


def pytest_configure(config):
    config.addinivalue_line("markers", "nli: uses the local NLI claim-verifier model (downloads it once)")
    config.addinivalue_line("markers", "presidio: uses Presidio + the spaCy model for PII detection")


@pytest.fixture(autouse=True)
def _claim_verifier_mode(request, monkeypatch):
    """Unit tests are hermetic: the semantic claim verifier (a local model) runs
    only in tests marked ``nli``; all others use the deterministic checks."""
    from config import settings

    if not request.node.get_closest_marker("nli"):
        monkeypatch.setattr(settings, "CLAIM_VERIFIER", "deterministic")


@pytest.fixture(autouse=True)
def _isolated_security_state(request, monkeypatch, tmp_path):
    """Security stores live in a per-test temporary directory (never the real
    backend/storage); the guardrail LLM self-check (a network call) is off unless a
    test enables it; PII uses the regex engine unless a test is marked ``presidio``."""
    from config import settings
    from security import sessions

    monkeypatch.setattr(settings, "USERS_FILE", str(tmp_path / "users.json"))
    monkeypatch.setattr(settings, "AUDIT_DIR", str(tmp_path / "audit"))
    monkeypatch.setattr(settings, "APPROVALS_FILE", str(tmp_path / "approvals.json"))
    monkeypatch.setattr(settings, "GUARDRAILS_LLM_SELF_CHECK", False)
    if not request.node.get_closest_marker("presidio"):
        monkeypatch.setattr(settings, "PII_ENGINE", "regex")
    sessions.clear()
    yield
    sessions.clear()
