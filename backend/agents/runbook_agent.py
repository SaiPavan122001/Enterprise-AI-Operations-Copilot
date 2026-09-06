"""Runbook retrieval agent.

The backend ships with curated markdown runbooks under data/runbooks/.
This agent picks the runbook that best matches the investigation question
and the matched incidents, so the RCA model can use operational guidance
as *supporting context* - never as unquestionable truth.
"""

import logging
import re

from models.evidence import RunbookEvidence
from utils.data_store import get_runbooks

logger = logging.getLogger(__name__)

MAX_RUNBOOK_CHARS = 4000

# Maps runbooks to the domains they cover. Keys are runbook file stems.
RUNBOOK_KEYWORDS: dict[str, list[str]] = {
    "database_timeout": [
        "database", "db", "timeout", "slow query", "query", "migration",
        "index", "connection pool", "sql",
    ],
    "email_delivery_failure": [
        "email", "smtp", "mail", "notification", "sms",
    ],
    "gateway_outage": [
        "gateway", "ingress", "outage", "502", "503", "unavailable",
        "api error", "error rate",
    ],
    "jwt_auth_failure": [
        "jwt", "auth", "login", "token", "sso", "oauth", "session",
        "certificate", "authentication",
    ],
    "payment_failure": [
        "payroll", "payment", "salary", "salary_amount", "billing",
    ],
}


def _tokenize(text: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9_]+", text.lower()) if len(t) > 2]


def retrieve_runbook(
    question: str, incidents: list
) -> RunbookEvidence | None:
    """Return the best-matching runbook as structured evidence, or None."""
    runbooks = get_runbooks()
    if not runbooks:
        return None

    incident_text = " ".join(
        f"{getattr(i, 'title', '') or ''} {getattr(i, 'root_cause', '') or ''} "
        f"{getattr(i, 'service', '') or ''}"
        for i in incidents
    )
    haystack = f"{question} {incident_text}".lower()
    tokens = set(_tokenize(haystack))

    best_name: str | None = None
    best_score = 0

    for name, keywords in RUNBOOK_KEYWORDS.items():
        if name not in runbooks:
            continue
        score = 0
        for keyword in keywords:
            if keyword in haystack:
                score += 2
            elif keyword in tokens:
                score += 1
        if score > best_score:
            best_score = score
            best_name = name

    if not best_name or best_score == 0:
        logger.info("Runbook agent: no runbook matched the investigation")
        return None

    title = runbooks[best_name].splitlines()[0].lstrip("# ").strip()
    content = runbooks[best_name][:MAX_RUNBOOK_CHARS]
    logger.info("Runbook agent selected '%s' (score=%d)", best_name, best_score)
    return RunbookEvidence(name=best_name, title=title, content=content)
