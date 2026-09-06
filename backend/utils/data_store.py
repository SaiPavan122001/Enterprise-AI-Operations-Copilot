"""Application-level cache for the static enterprise data files.

The deployments, logs and runbooks change rarely, so they are loaded once
and cached in memory instead of being re-read and re-parsed on every
request. Paths are resolved relative to the backend package, so the app
works regardless of the current working directory.
"""

import json
import logging
from functools import lru_cache
from pathlib import Path

from config import DATA_DIR, RUNBOOKS_DIR

logger = logging.getLogger(__name__)

MAX_LOG_LINES = 60


@lru_cache(maxsize=1)
def get_deployments() -> list[dict]:
    path = DATA_DIR / "deployments.json"
    try:
        with open(path, "r", encoding="utf-8") as f:
            deployments = json.load(f)
        logger.info("Loaded %d deployments from cache", len(deployments))
        return deployments
    except (OSError, json.JSONDecodeError):
        logger.exception("Failed to load deployments from %s", path)
        return []


@lru_cache(maxsize=1)
def get_logs() -> list[str]:
    path = DATA_DIR / "logs.txt"
    try:
        with open(path, "r", encoding="utf-8") as f:
            logs = [line.rstrip("\n") for line in f if line.strip()]
        logger.info("Loaded %d log lines into cache", len(logs))
        return logs
    except OSError:
        logger.exception("Failed to load logs from %s", path)
        return []


@lru_cache(maxsize=1)
def get_runbooks() -> dict[str, str]:
    """Return {runbook_name: content} for every markdown runbook."""
    runbooks: dict[str, str] = {}
    if not RUNBOOKS_DIR.is_dir():
        logger.warning("Runbooks directory not found: %s", RUNBOOKS_DIR)
        return runbooks
    for path in sorted(RUNBOOKS_DIR.glob("*.md")):
        try:
            runbooks[path.stem] = path.read_text(encoding="utf-8")
        except OSError:
            logger.exception("Failed to read runbook %s", path)
    logger.info("Loaded %d runbooks into cache", len(runbooks))
    return runbooks


def refresh_data_cache() -> None:
    """Clear all caches so the next access re-reads from disk."""
    get_deployments.cache_clear()
    get_logs.cache_clear()
    get_runbooks.cache_clear()
    logger.info("Enterprise data cache cleared")


def trim_logs(lines: list[str], limit: int = MAX_LOG_LINES) -> list[str]:
    """Keep the most relevant log lines, newest last, capped in count."""
    if len(lines) <= limit:
        return lines
    return lines[-limit:]
