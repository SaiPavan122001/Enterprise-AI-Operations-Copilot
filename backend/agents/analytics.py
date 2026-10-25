"""Aggregate questions ("where are most tickets happening?", "how many critical
incidents?") answered by COUNTING the records the principal may read.

The RCA pipeline answers questions about one problem: it retrieves the incidents
that describe it. An aggregate question describes no single problem, so retrieval
correctly finds nothing - these questions are routed here instead.

Deterministic, no LLM: every number is a count over incidents.json /
deployments.json / logs.txt, restricted to the principal's services, and every
statement cites the incident IDs it counts.
"""

import re
from collections import Counter

from models.evidence import IncidentEvidence

_NOUN = r"(?:incidents?|tickets?|issues?|outages?|failures?|problems?|alerts?|errors?|deployments?)"
AGGREGATE_RE = re.compile(
    r"\b(?:how many|number of|count of|total)\b[^.?!]{0,30}\b" + _NOUN + r"\b"
    r"|\b(?:most|fewest|least|more|highest number of)\s+(?:\w+\s+){0,2}" + _NOUN + r"\b"
    r"|\b" + _NOUN + r"\s+(?:by|per)\s+(?:service|severity|status|team|area|component|system)\b"
    r"|\b(?:breakdown|distribution|statistics|stats|trends?|overview|summary|patterns?|hot\s?spots?)\s+"
    r"(?:of|for|in|across)\s+(?:\w+\s+){0,3}" + _NOUN + r"\b"
    r"|\b" + _NOUN + r"\s+(?:trends?|patterns?|hot\s?spots?|statistics|stats|breakdown|distribution)\b"
    r"|\bwhere\b[^.?!]{0,40}\b(?:most|majority)\b"
    r"|\bwhich\s+(?:service|team|area|component|system|part)s?\b[^.?!]{0,40}\b(?:most|frequent\w*|often|more)\b"
    r"|\b(?:most|frequently)\s+(?:affected|impacted|failing|problematic)\s+(?:service|team|area|component|system)s?\b",
    re.IGNORECASE)
_SEVERITY_ORDER = ["Critical", "High", "Medium", "Low"]
_LOG_RE = re.compile(r"^(\S+ \S+)\s+(\S+)\s+(ERROR|CRITICAL|WARN)\b")


def is_aggregate_question(question: str) -> bool:
    return bool(AGGREGATE_RE.search(question or ""))


def _ids(incidents: list[dict]) -> list[str]:
    return sorted(i["id"] for i in incidents)


def _join(items) -> str:
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def answer(question: str, principal) -> dict:
    """Counts over the authorized records. Returns the parts of an answer:
    summary, facts (with refs), unknowns, markdown, incidents (IncidentEvidence)."""
    from agents.deployment_agent import deployment_link_status
    from security import access
    from utils.data_store import get_incidents, get_logs

    incidents = access.filter_by_service(principal, get_incidents())
    evidence = [IncidentEvidence(incident_id=i["id"], service=i.get("service"), severity=i.get("severity"),
                                 status=i.get("status"), title=i.get("title"), root_cause=i.get("root_cause"),
                                 deployment_id=i.get("deployment_id")) for i in incidents]
    if not incidents:
        return {"summary": "There are no incident records you are authorized to read, so nothing can be counted.",
                "facts": [], "unknowns": [], "markdown": "", "incidents": []}

    by_service = Counter(i["service"] for i in incidents)
    ranked = by_service.most_common()
    top_n = ranked[0][1]
    leaders = [s for s, n in ranked if n == top_n]
    by_sev = Counter(i.get("severity") or "Unknown" for i in incidents)
    open_ = [i for i in incidents if (i.get("status") or "").lower() not in ("resolved", "closed")]
    linked = [i for i in incidents if deployment_link_status(i)[0] in ("verified", "documented_dependency")]
    services_ok = {s for s, _ in ranked}
    errors: Counter[str] = Counter()
    first = last = None
    for line in get_logs():
        m = _LOG_RE.match(line)
        if m and m.group(2) in services_ok:
            errors[m.group(2)] += 1
            first = min(first or m.group(1), m.group(1))
            last = max(last or m.group(1), m.group(1))

    def svc_ids(service: str) -> list[str]:
        return _ids([i for i in incidents if i["service"] == service])

    total = len(incidents)
    others = [f"{s} ({n})" for s, n in ranked if s not in leaders]
    if len(leaders) == 1:
        service_line = f"{leaders[0]} has the most incidents: {top_n} of {total}."
        if others:
            service_line += f" Next: {_join(others[:3])}."
    elif len(leaders) * 2 >= len(ranked):
        service_line = (f"Incidents are spread fairly evenly across services: {len(leaders)} services have "
                        f"{top_n} each ({_join(leaders)})"
                        + (f", while {_join(f'{x} has {n}' for x, n in ranked if x not in leaders)}" if others else "")
                        + ".")
    else:
        service_line = f"{_join(leaders)} have the most incidents ({top_n} each)."
    critical = Counter(i["service"] for i in incidents if i.get("severity") == "Critical")
    if critical:
        top_c = max(critical.values())
        crit_leaders = sorted(s for s, n in critical.items() if n == top_c)
        service_line += (f" The most severe hotspot is {_join(crit_leaders)}, with {top_c} of the "
                         f"{sum(critical.values())} Critical incidents.")
    sev_line = "By severity: " + ", ".join(f"{by_sev[s]} {s}" for s in _SEVERITY_ORDER if by_sev.get(s)) + "."
    asked_levels = [s for s in _SEVERITY_ORDER if re.search(rf"\b{s}\b", question or "", re.IGNORECASE)]
    if asked_levels:
        sev_line = " ".join(
            f"There {'is' if by_sev.get(s, 0) == 1 else 'are'} {_plural(by_sev.get(s, 0), s + ' incident')} "
            f"(of {total})" + (": " + _join(f"{svc} {n}" for svc, n in Counter(
                i["service"] for i in incidents if i.get("severity") == s).most_common()) if by_sev.get(s) else "")
            + "." for s in asked_levels)
    deploy_line = (f"{len(linked)} of {total} are linked to a verified deployment, so "
                   f"{'most' if len(linked) * 2 > total else 'fewer than half'} trace back to a recorded change.")
    per_dep = Counter(i["deployment_id"] for i in linked)
    if per_dep:
        top_d = max(per_dep.values())
        deploy_line += (f" {_join(sorted(d for d, n in per_dep.items() if n == top_d))} "
                        f"{'is' if sum(n == top_d for n in per_dep.values()) == 1 else 'are'} linked to the most "
                        f"incidents ({top_d})." if top_d > 1 else
                        " Each of those deployments is linked to exactly one incident.")
    status_line = (f"{len(open_)} of {total} are not yet resolved." if open_
                   else f"All {total} are recorded as resolved.")
    if errors:
        top_e = max(errors.values())
        status_line += (f" {_join(sorted(s for s, n in errors.items() if n == top_e))} logged the most "
                        f"error and warning lines ({top_e}).")
    q = (question or "").lower()
    if asked_levels or "severity" in q or "critical" in q:
        order = [sev_line, service_line, deploy_line]
    elif re.search(r"\bdeploy|\bchange|\brelease", q):
        order = [deploy_line, service_line, sev_line]
    elif re.search(r"\bopen\b|unresolved|resolved|status|pending", q):
        order = [status_line, service_line, sev_line]
    else:
        order = [service_line, sev_line, deploy_line, status_line]
    summary = f"Counted over the {_plural(total, 'incident record')} you can access. " + " ".join(order)

    facts = [{"statement": f"{s}: {_plural(n, 'incident')}", "refs": svc_ids(s)} for s, n in ranked]
    facts += [{"statement": f"{s} severity: {by_sev[s]}", "refs": _ids([i for i in incidents
                                                                         if i.get("severity") == s])}
              for s in _SEVERITY_ORDER if by_sev.get(s)]
    facts.append({"statement": f"Linked to a verified deployment: {len(linked)}", "refs": _ids(linked)})
    if open_:
        facts.append({"statement": f"Not resolved: {len(open_)}", "refs": _ids(open_)})

    unknowns = ["Incident records carry no dates, so the counts cover all recorded incidents; a recent-period "
                "trend cannot be computed from them."]
    if first:
        unknowns.append(f"Error and warning log lines on these services span {first} to {last}.")

    table = ["| Service | Incidents | Critical | High | Error/warn log lines |", "|---|---|---|---|---|"]
    for s, n in ranked:
        sev = Counter(i.get("severity") for i in incidents if i["service"] == s)
        table.append(f"| {s} | {n} | {sev.get('Critical', 0)} | {sev.get('High', 0)} | {errors.get(s, 0)} |")
    markdown = (f"## Incident overview\n\n{order[0]}\n\n" + "".join(f"- {line}\n" for line in order[1:])
                + "\n" + "\n".join(table) + "\n\n"
                + f"_Counted over the {_plural(total, 'incident record')} you can access. "
                + " ".join(unknowns) + "_\n")
    return {"summary": summary, "facts": facts, "unknowns": unknowns, "markdown": markdown, "incidents": evidence}


def analytics_result(bundle, validation, principal):
    """The API result for an aggregate question (answer_source="analytics")."""
    from models.evidence import InvestigationResult

    parts = answer(bundle.question, principal)
    found = bool(parts["incidents"])
    bundle = bundle.model_copy(update={"incident_evidence": parts["incidents"]})
    validation = validation.model_copy(update={
        "incident_found": found, "evidence_strength": "HIGH" if found else "INSUFFICIENT",
        "missing_evidence": [], "contradictions": [],
        "notes": ["Counted over every incident record you are authorized to read (no retrieval ranking)."]})
    return InvestigationResult(
        question=bundle.question, summary=parts["summary"], root_cause=None,
        impact="Not applicable: this is a count over incident records, not a single investigation.",
        confidence="HIGH" if found else "INSUFFICIENT", evidence_strength=validation.evidence_strength,
        observed_evidence=[f"{f['statement']} [{', '.join(f['refs'])}]" for f in parts["facts"]],
        unknowns=parts["unknowns"], evidence=bundle, validation=validation, report_markdown=parts["markdown"],
        answer_status="answered" if found else "insufficient_evidence", answer_source="analytics")
