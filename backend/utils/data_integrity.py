"""Integrity checks for the incident / deployment / log relationships.

Severity levels:
* ``error``      - the dataset is unusable (duplicate IDs, missing required
                   fields, unparseable deployment times). Ingestion fails.
* ``quarantine`` - a *relationship* cannot be trusted: an incident references a
                   deployment that does not exist, or one that belongs to a
                   different service without a documented dependency. The
                   incident stays searchable, but the deployment is NOT joined
                   to it, and the RCA reports the link as unverified. Every
                   quarantined link must be listed in ``data_quality_review.json``
                   (manual review queue) or ingestion fails.
* ``warning``    - weak or missing corroborating data (no logs for a service,
                   log messages that appear on every service, logs from
                   unknown services). Reported, never fatal.
* ``info``       - a cross-service link accepted because a documented
                   dependency exists in ``service_dependencies.json``.

Nothing here guesses a replacement relationship: quarantined links are only
reported, never rewritten.
"""

import json
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache

from config import DATA_DIR

logger = logging.getLogger(__name__)

REQUIRED_INCIDENT_FIELDS = ("id", "service", "severity", "status", "title", "root_cause")
REQUIRED_DEPLOYMENT_FIELDS = ("deployment_id", "service", "time", "change")
KNOWN_SEVERITIES = ("Critical", "High", "Medium", "Low")
LOG_LINE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+([\w-]+)\s+([A-Z]+)\s+(.*)$")
# A non-INFO log message seen on at least this many distinct services carries
# no service-specific signal.
NON_SPECIFIC_MESSAGE_MIN_SERVICES = 3


@dataclass
class IntegrityIssue:
    severity: str          # error | quarantine | warning | info
    code: str
    record_id: str
    message: str
    evidence: dict = field(default_factory=dict)


@dataclass
class IntegrityReport:
    issues: list[IntegrityIssue] = field(default_factory=list)
    # incident_id -> verified deployment dict (same service or documented dependency)
    verified_links: dict[str, dict] = field(default_factory=dict)
    # incident_id -> quarantine issue
    quarantined_links: dict[str, IntegrityIssue] = field(default_factory=dict)
    non_specific_log_messages: set[str] = field(default_factory=set)

    def by_severity(self, severity: str) -> list[IntegrityIssue]:
        return [i for i in self.issues if i.severity == severity]

    @property
    def ok(self) -> bool:
        return not self.by_severity("error")


def load_dependencies(path=None) -> set[tuple[str, str]]:
    """Documented service dependencies: {(service, depends_on)}. Each entry
    must cite its source; undocumented entries are rejected."""
    path = path or DATA_DIR / "service_dependencies.json"
    if not path.exists():
        return set()
    data = json.loads(path.read_text(encoding="utf-8"))
    deps = set()
    for entry in data.get("dependencies", []):
        if not entry.get("source"):
            raise ValueError(f"Service dependency {entry} has no 'source' - undocumented "
                             "dependencies are not accepted")
        deps.add((entry["service"], entry["depends_on"]))
    return deps


def load_review_decisions(path=None) -> dict[str, dict]:
    path = path or DATA_DIR / "data_quality_review.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {r["incident_id"]: r for r in data.get("records", [])}


def parse_log_line(line: str):
    m = LOG_LINE_RE.match(line.strip())
    if not m:
        return None
    try:
        datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return {"timestamp": m.group(1), "service": m.group(2), "level": m.group(3).upper(),
            "message": m.group(4).strip()}


def check_integrity(incidents: list[dict], deployments: list[dict], log_lines: list[str],
                    dependencies: set[tuple[str, str]] | None = None,
                    review_decisions: dict[str, dict] | None = None) -> IntegrityReport:
    dependencies = dependencies or set()
    review_decisions = review_decisions or {}
    report = IntegrityReport()
    add = report.issues.append

    # --- record-level errors
    seen = set()
    content_seen: dict[tuple, str] = {}
    for inc in incidents:
        missing = [f for f in REQUIRED_INCIDENT_FIELDS if not inc.get(f)]
        if missing:
            add(IntegrityIssue("error", "incident_missing_fields", inc.get("id", "?"),
                               f"missing fields {missing}"))
        bad_types = [f for f in REQUIRED_INCIDENT_FIELDS + ("deployment_id",)
                     if inc.get(f) is not None and not isinstance(inc.get(f), str)]
        if bad_types:
            add(IntegrityIssue("error", "incident_bad_type", str(inc.get("id", "?")),
                               f"fields must be strings: {bad_types}"))
        if inc.get("id") in seen:
            add(IntegrityIssue("error", "duplicate_incident_id", inc["id"], "duplicate incident id"))
        seen.add(inc.get("id"))
        if inc.get("severity") and inc.get("severity") not in KNOWN_SEVERITIES:
            add(IntegrityIssue("warning", "unknown_severity", str(inc.get("id", "?")),
                               f"severity {inc.get('severity')!r} not in {KNOWN_SEVERITIES}"))
        key = (inc.get("service"), str(inc.get("title", "")).strip().lower(),
               str(inc.get("root_cause", "")).strip().lower())
        if all(key) and key in content_seen:
            add(IntegrityIssue("warning", "possible_duplicate_incident", str(inc.get("id", "?")),
                               f"same service/title/root cause as {content_seen[key]}"))
        content_seen.setdefault(key, str(inc.get("id", "?")))

    deps_by_id: dict[str, dict] = {}
    for record in deployments:
        did = record.get("deployment_id", "?")
        missing = [f for f in REQUIRED_DEPLOYMENT_FIELDS if not record.get(f)]
        if missing:
            add(IntegrityIssue("error", "deployment_missing_fields", did, f"missing fields {missing}"))
        try:
            datetime.fromisoformat(record.get("time", ""))
        except ValueError:
            add(IntegrityIssue("error", "deployment_bad_time", did, f"unparseable time {record.get('time')!r}"))
        if did in deps_by_id:
            add(IntegrityIssue("error", "duplicate_deployment_id", did, "duplicate deployment id"))
        deps_by_id[did] = record

    # --- incident -> deployment relationships
    for inc in incidents:
        iid, did = inc.get("id", "?"), inc.get("deployment_id")
        if not did:
            continue
        dep = deps_by_id.get(did)
        if dep is None:
            issue = IntegrityIssue("quarantine", "deployment_missing", iid,
                                   f"references {did}, which does not exist in deployments.json",
                                   {"deployment_id": did})
        elif dep.get("service") == inc.get("service"):
            report.verified_links[iid] = dep
            continue
        elif (inc.get("service"), dep.get("service")) in dependencies:
            report.verified_links[iid] = dep
            add(IntegrityIssue("info", "cross_service_dependency", iid,
                               f"{did} is on {dep['service']}; accepted via documented dependency "
                               f"{inc['service']} -> {dep['service']}",
                               {"deployment_id": did, "deployment_service": dep["service"]}))
            continue
        else:
            issue = IntegrityIssue(
                "quarantine", "deployment_service_mismatch", iid,
                f"incident is on {inc.get('service')} but references {did}, a "
                f"{dep.get('service')} deployment ({dep.get('change')!r}); no documented dependency",
                {"deployment_id": did, "incident_service": inc.get("service"),
                 "deployment_service": dep.get("service"), "deployment_change": dep.get("change")})
        reviewed = review_decisions.get(iid)
        if reviewed is None:
            add(IntegrityIssue("error", "unreviewed_quarantine", iid,
                               f"{issue.message} - add it to data_quality_review.json or fix the data",
                               issue.evidence))
        elif reviewed.get("referenced_deployment_id") != did:
            # A review covers one exact (incident, deployment) pair: changing the link to
            # another unverified deployment must not inherit the old review.
            add(IntegrityIssue("error", "stale_quarantine_review", iid,
                               f"review covers {reviewed.get('referenced_deployment_id')} but the data now "
                               f"references {did} - review the new link", issue.evidence))
        add(issue)
        report.quarantined_links[iid] = issue

    # --- logs
    parsed = [p for p in (parse_log_line(line) for line in log_lines) if p]
    unparseable = sum(1 for line in log_lines if line.strip()) - len(parsed)
    if unparseable:
        add(IntegrityIssue("warning", "unparseable_log_lines", "logs.txt",
                           f"{unparseable} log line(s) could not be parsed (format or timestamp)"))
    services_with_logs = {p["service"] for p in parsed}
    known_services = {i.get("service") for i in incidents} | {d.get("service") for d in deployments}
    for svc in sorted(s for s in known_services if s and s not in services_with_logs):
        add(IntegrityIssue("warning", "no_logs_for_service", svc, "no log lines for this service"))
    for svc in sorted(services_with_logs - known_services):
        add(IntegrityIssue("warning", "unknown_log_service", svc,
                           "log lines reference a service with no incidents or deployments"))
    msg_services: dict[str, set] = defaultdict(set)
    for p in parsed:
        if p["level"] != "INFO":
            msg_services[p["message"]].add(p["service"])
    for msg, svcs in sorted(msg_services.items()):
        if len(svcs) >= NON_SPECIFIC_MESSAGE_MIN_SERVICES:
            report.non_specific_log_messages.add(msg)
            add(IntegrityIssue("warning", "log_message_not_service_specific", msg[:60],
                               f"appears on {len(svcs)} services; cannot corroborate a specific service",
                               {"services": sorted(svcs)}))
    return report


def load_provenance(path=None) -> dict:
    """Dataset provenance from data_quality_review.json: status is "real",
    "synthetic" or "unconfirmed" (the default when nobody has confirmed it)."""
    path = path or DATA_DIR / "data_quality_review.json"
    if not path.exists():
        return {"status": "unconfirmed"}
    data = json.loads(path.read_text(encoding="utf-8"))
    prov = (data.get("dataset_assessment") or {}).get("provenance") or {}
    return {**prov, "status": prov.get("status") if prov.get("status") in ("real", "synthetic") else "unconfirmed"}


def strict_problems(report: IntegrityReport, review_decisions: dict[str, dict] | None = None,
                    provenance: dict | None = None) -> list[str]:
    """Why the data is NOT fit for strict (production) ingestion. Default seeding
    accepts reviewed quarantines; strict seeding accepts only data whose links all
    verify, whose logs carry service-specific signal and whose provenance an owner
    has confirmed. Nothing here repairs data."""
    review_decisions = review_decisions if review_decisions is not None else load_review_decisions()
    provenance = provenance if provenance is not None else load_provenance()
    problems = [f"{i.record_id}: {i.message}" for i in report.by_severity("error")]
    for iid in sorted(report.quarantined_links):
        status = (review_decisions.get(iid) or {}).get("status", "unreviewed")
        problems.append(f"{iid}: deployment link quarantined ({status}) - needs a reviewer decision applied "
                        "to incidents.json")
    if report.non_specific_log_messages:
        problems.append(f"logs: {len(report.non_specific_log_messages)} non-INFO message(s) appear on several "
                        "services and cannot corroborate a specific incident")
    if provenance["status"] != "real":
        problems.append(f"provenance: dataset provenance is {provenance['status']} - strict ingestion requires "
                        "an owner to confirm the records are real")
    return problems


def report_summary(report: IntegrityReport) -> dict:
    return {
        "ok": report.ok,
        "counts": {s: len(report.by_severity(s)) for s in ("error", "quarantine", "warning", "info")},
        "verified_links": sorted(report.verified_links),
        "quarantined_links": sorted(report.quarantined_links),
        "provenance": load_provenance()["status"],
        "issues": [vars(i) for i in report.issues],
    }


def write_report(report: IntegrityReport, path=None) -> str:
    """Persist the integrity report so validation results are observable
    after ingestion (backend/storage/ is git-ignored)."""
    path = path or DATA_DIR.parent / "storage" / "integrity_report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report_summary(report), indent=2, default=str), encoding="utf-8")
    logger.info("Integrity report written to %s", path)
    return str(path)


@lru_cache(maxsize=1)
def get_integrity_report() -> IntegrityReport:
    """Integrity report for the application's data files (cached)."""
    from utils.data_store import get_deployments, get_logs

    incidents = json.loads((DATA_DIR / "incidents.json").read_text(encoding="utf-8"))
    report = check_integrity(incidents, get_deployments(), get_logs(),
                             load_dependencies(), load_review_decisions())
    for issue in report.by_severity("quarantine"):
        logger.warning("Data integrity: %s quarantined (%s): %s", issue.record_id, issue.code, issue.message)
    for issue in report.by_severity("error"):
        logger.error("Data integrity ERROR: %s (%s): %s", issue.record_id, issue.code, issue.message)
    return report
