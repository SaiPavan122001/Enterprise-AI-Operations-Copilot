import logging
import re

from models.evidence import LogEvidence
from utils.data_store import get_logs

logger = logging.getLogger(__name__)

MAX_LOG_EVIDENCE = 40

# logs.txt line format: "YYYY-MM-DD HH:MM:SS service LEVEL message"
LOG_LINE_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+"
    r"(?P<service>[\w-]+)\s+"
    r"(?P<level>INFO|WARN|WARNING|ERROR|CRITICAL|EXCEPTION)\s+"
    r"(?P<message>.*)$",
    re.IGNORECASE,
)

# Severity ranking used to prioritise signals over noise.
LEVEL_PRIORITY = {"ERROR": 0, "CRITICAL": 0, "EXCEPTION": 0, "WARN": 1, "WARNING": 1}

# Extra error-related terms that boost a line's relevance.
ERROR_TERMS = (
    "fail", "failed", "failure", "timeout", "timed out", "connection",
    "database", "migration", "refused", "unavailable", "exception",
)


def _parse_line(line: str) -> LogEvidence:
    match = LOG_LINE_RE.match(line)
    if match:
        level = match.group("level").upper()
        return LogEvidence(
            timestamp=match.group("ts"),
            service=match.group("service"),
            level="WARN" if level == "WARNING" else level,
            message=match.group("message").strip(),
        )
    # Unparseable line: preserve the original text, no fabricated fields.
    return LogEvidence(message=line.rstrip())


def _relevance(entry: LogEvidence, terms: set[str]) -> int:
    text = f"{entry.service or ''} {entry.message}".lower()
    score = 0
    if entry.level in LEVEL_PRIORITY:
        score += 3 - LEVEL_PRIORITY[entry.level]  # ERROR > WARN
    for term in terms:
        if term and term in text:
            score += 2
    if any(term in text for term in ERROR_TERMS):
        score += 1
    return score


def investigate_logs(
    incidents: list,  # list[IncidentEvidence]
    keywords: list[str] | None = None,
    deployments: list | None = None,  # list[DeploymentEvidence]
) -> list[LogEvidence]:
    """Retrieve structured log evidence relevant to the investigation.

    Matching uses everything already discovered: incident services,
    deployment services and question keywords. ERROR/WARN lines and known
    error terms are prioritised over INFO noise, and the result is capped
    so the raw log file is never dumped into the LLM context.
    """
    logs = get_logs()
    if not logs:
        return []

    services = set()
    for incident in incidents:
        service = getattr(incident, "service", None) or (
            incident.get("service") if isinstance(incident, dict) else None
        )
        if service:
            services.add(service)
    for deployment in deployments or []:
        service = getattr(deployment, "service", None) or (
            deployment.get("service") if isinstance(deployment, dict) else None
        )
        if service:
            services.add(service)

    terms = services | {k.lower() for k in (keywords or [])}
    if not terms:
        logger.info("Log agent: no services/keywords to match, skipping")
        return []

    candidates: list[tuple[int, LogEvidence]] = []
    for line in logs:
        entry = _parse_line(line)
        text = f"{entry.service or ''} {entry.message}".lower()
        if any(term.lower() in text for term in terms):
            candidates.append((_relevance(entry, terms), entry))

    if not candidates:
        logger.info("Log agent found no relevant lines")
        return []

    # ERROR/WARN and high-signal lines first, then chronological recency.
    candidates.sort(key=lambda item: (-item[0], item[1].timestamp or ""))
    selected = [entry for _, entry in candidates[:MAX_LOG_EVIDENCE]]

    logger.info(
        "Log agent selected %d/%d relevant lines (services=%s)",
        len(selected), len(candidates), services or "{}",
    )
    return selected
