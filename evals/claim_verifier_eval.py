"""Measure runtime claim-support validation on claims whose label is known BY
CONSTRUCTION from the data.

    python -m evals.claim_verifier_eval [--mode nli|deterministic]

For every incident a bundle is built the way production builds it (the incident,
its verified deployment if any, no corroborating logs - true for every incident
in this dataset - and the quarantine note when its link is quarantined). Each
claim cites that incident and is put through the production validator
(``rca_structured.validate``) as a confirmed fact ("stated" policy) and as a
conclusion ("inferred" policy). A claim is FLAGGED if it does not survive in its
section (removed or moved to hypotheses).

Supported claims include the patterns real answers use (multi-fact restatements,
"no log lines corroborate ...", quarantine facts), which were false-positive
sources for the first version of the verifier. Unsupported claims are
adversarial: another incident's cause/title/service, wrong severity/status,
negated cause, invented figures, deployment causation, a false verified link,
a false absence.

Limits: template claims; labels follow from the data, not from a human. No
human-labelled real claims exist yet (evals/calibration/claim_labels.csv).
Writes evals/results/claim_verifier_eval.json and evals/calibration/claim_verifier_labelled.csv.
"""

import argparse
import csv
import json
import sys

from evals.settings import repo_path


def _lc(s: str) -> str:
    return s[:1].lower() + s[1:]


def build_cases(incidents: list[dict], links: dict[str, tuple[str, str | None, dict | None]]) -> list[dict]:
    """links: incident id -> (status, detail, deployment dict)"""
    cases = []
    sev_other = {"Critical": "medium", "High": "critical", "Medium": "critical", "Low": "high"}
    for n, i in enumerate(incidents):
        j = next(x for x in incidents[n + 1:] + incidents[:n] if x["service"] != i["service"])
        iid, svc = i["id"], i["service"]
        status, _, dep = links[iid]
        sup = {
            "title": f'{iid} recorded the problem "{i["title"]}".',
            "root_cause": f"The recorded root cause of {iid} was {_lc(i['root_cause'])}.",
            "service": f"{iid} occurred on the {svc}.",
            "severity": f"{iid} was a {i['severity'].lower()}-severity incident.",
            "status": f"{iid} has been resolved.",
            "paraphrase": f"{i['title']} on the {svc} was attributed to {_lc(i['root_cause'])}.",
            "compound_restatement": (f"{iid} on {svc} was a {i['severity']} severity incident titled "
                                     f"'{i['title']}' with a recorded root cause of {_lc(i['root_cause'])}."),
            "absence_logs": f"No log lines on {svc} corroborate {iid}.",
        }
        uns = {
            "cause_swap": f"The recorded root cause of {iid} was {_lc(j['root_cause'])}.",
            "title_swap": f'{iid} recorded the problem "{j["title"]}".',
            "service_swap": f"{iid} occurred on the {j['service']}.",
            "severity_swap": f"{iid} was a {sev_other[i['severity']]}-severity incident.",
            "negated_cause": f"The root cause of {iid} was not {_lc(i['root_cause'])}.",
            "invented_metric": f"{iid} affected 4,200 users for 3 hours.",
            "deployment_causation": f"{iid} was caused by a faulty deployment.",
            "status_wrong": f"{iid} is still unresolved.",
            "false_absence": f"No root cause was recorded for {iid}.",
        }
        if status == "verified":
            sup["linked_deployment"] = f"{iid} is linked to deployment {dep['deployment_id']} on the {svc}."
        else:
            sup["absence_link"] = f"No verified deployment link exists for {iid}."
            if status == "quarantined":
                sup["quarantine_fact"] = (f"The deployment link {dep['deployment_id']} for {iid} is quarantined "
                                          f"because it belongs to {dep['service']}, not {svc}.")
                uns["false_verified_link"] = f"{iid} is linked to verified deployment {dep['deployment_id']}."
        cases += [{"incident_id": iid, "label": "supported", "category": k, "statement": v} for k, v in sup.items()]
        cases += [{"incident_id": iid, "label": "unsupported", "category": k, "statement": v}
                  for k, v in uns.items()]
    return cases


def score(cases: list[dict], key: str) -> dict:
    tp = sum(1 for c in cases if c["label"] == "unsupported" and c[key])
    fp = sum(1 for c in cases if c["label"] == "supported" and c[key])
    fn = sum(1 for c in cases if c["label"] == "unsupported" and not c[key])
    tn = sum(1 for c in cases if c["label"] == "supported" and not c[key])
    r3 = lambda x: round(x, 3)  # noqa: E731
    per_cat = {}
    for c in cases:
        d = per_cat.setdefault(f"{c['label']}/{c['category']}", [0, 0])
        d[0] += int(c[key])
        d[1] += 1
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": r3(tp / (tp + fp)) if tp + fp else None,
            "recall": r3(tp / (tp + fn)) if tp + fn else None,
            "false_positive_rate": r3(fp / (fp + tn)) if fp + tn else None,
            "flag_rate_by_category": {k: f"{a}/{b}" for k, (a, b) in sorted(per_cat.items())}}


def link_table() -> tuple[list[dict], dict]:
    """incidents.json records and, per incident, (link status, detail, deployment)."""
    from agents.deployment_agent import deployment_link_status
    from utils.data_store import get_deployments

    incidents = json.load(open(repo_path("backend/data/incidents.json"), encoding="utf-8"))
    deployments = {d["deployment_id"]: d for d in get_deployments()}
    links = {}
    for i in incidents:
        status, detail = deployment_link_status(i)
        links[i["id"]] = (status, detail, deployments.get(i.get("deployment_id")))
    return incidents, links


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m evals.claim_verifier_eval")
    p.add_argument("--mode", choices=["nli", "deterministic"], default="nli")
    p.add_argument("--file", help="score a labelled JSONL (e.g. the unseen held-out set) instead of the templates")
    p.add_argument("--tag", default="", help="suffix for the output files")
    args = p.parse_args(argv)

    from agents import rca_structured as rs
    from agents.deployment_agent import investigate_deployments
    from config import settings
    from models.evidence import EvidenceBundle, EvidenceValidation, IncidentEvidence

    settings.CLAIM_VERIFIER = args.mode
    incidents, links = link_table()
    if args.file:
        cases = [json.loads(line) for line in open(args.file, encoding="utf-8") if line.strip()]
    else:
        cases = build_cases(incidents, links)
    by_id = {i["id"]: i for i in incidents}
    for c in cases:
        i = by_id[c["incident_id"]]
        inc = IncidentEvidence(incident_id=i["id"], service=i["service"], severity=i["severity"],
                               status=i["status"], title=i["title"], root_cause=i["root_cause"],
                               deployment_id=i.get("deployment_id"))
        bundle = EvidenceBundle(question=f"Why did {i['title'].lower()} happen?", incident_evidence=[inc],
                                deployment_evidence=investigate_deployments([inc]))
        status, detail, _ = links[i["id"]]
        validation = EvidenceValidation(
            evidence_strength="MEDIUM",
            missing_evidence=["No log lines corroborate the matched incident."]
            + ([f"Deployment link not used: {detail}"] if detail else []))
        claim = {"statement": c["statement"], "refs": [i["id"]]}
        for section, key in (("confirmed_facts", "flag_stated"), ("conclusions", "flag_inferred")):
            data = {"answer_status": "answered", "summary": f"{i['title']} [{i['id']}].",
                    "confirmed_facts": [], "conclusions": [], "hypotheses": [], "impact": [],
                    "contributing_factors": [], "limitations": [], "unknowns": [],
                    "root_cause": {"status": "determined", "statement": i["root_cause"], "refs": [i["id"]]},
                    "recommended_remediation": [], "preventive_actions": [], "confidence": "LOW",
                    "confidence_reason": "", section: [claim]}
            clean, issues = rs.validate(data, bundle, validation, [], dependencies=set())
            if any("semantic verifier unavailable" in x for x in issues):
                raise SystemExit("NLI model unavailable - cannot measure the semantic verifier")
            c[key] = not any(x["statement"] == c["statement"] for x in clean[section])
            if section == "confirmed_facts":
                c["issues"] = " | ".join(x for x in issues if c["statement"][:40] in x)

    out = {"mode": args.mode, "model": settings.CLAIM_VERIFIER_MODEL if args.mode == "nli" else None,
           "n": len(cases), "n_supported": sum(c["label"] == "supported" for c in cases),
           "n_unsupported": sum(c["label"] == "unsupported" for c in cases),
           "labels": ("carried over from templates; LLM-reworded unseen claims" if args.file else
                      "by construction from backend/data (template claims)") + ", through rca_structured.validate",
           "source": args.file or "templates (development set)",
           "stated_policy": score(cases, "flag_stated"), "inferred_policy": score(cases, "flag_inferred")}
    suffix = ("" if args.mode == "nli" else f"_{args.mode}") + (f"_{args.tag}" if args.tag else "")
    with open(repo_path(f"evals/results/claim_verifier_eval{suffix}.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    with open(repo_path(f"evals/calibration/claim_verifier_labelled{suffix}.csv"), "w", newline="",
              encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(cases[0]))
        w.writeheader()
        w.writerows(cases)
    for k in ("stated_policy", "inferred_policy"):
        s = out[k]
        print(f"{args.mode:13s} {k:16s} precision={s['precision']} recall={s['recall']} "
              f"FPR={s['false_positive_rate']} (tp={s['tp']} fp={s['fp']} fn={s['fn']} tn={s['tn']})")
    print(json.dumps(out["stated_policy"]["flag_rate_by_category"], indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
