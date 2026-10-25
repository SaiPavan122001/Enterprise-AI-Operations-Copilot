"""Human review of quarantined incident -> deployment links.

    python -m scripts.link_review export            # LINK_REVIEW.md + link_decisions.csv (reviewer fields empty)
    python -m scripts.link_review check             # validate the filled-in CSV, print the plan (no writes)
    python -m scripts.link_review apply --apply     # apply VALID reviewer decisions to incidents.json

Decisions (column "decision"; leave empty while pending):
  replace          set the incident's deployment_id to "new_deployment_id" - it must exist and be on
                   the incident's service (or a documented dependency), i.e. it must VERIFY
  none             the incident has no deployment - only when the reviewer confirms it
  keep_quarantined keep the current link quarantined (no data change)
"replace" and "none" require "reviewer" and "source" (where the reviewer confirmed it). Nothing is
inferred: rows without a decision are skipped, invalid rows are rejected, and the original
incidents.json is copied to backend/data/versions/ before any change.
"""

import csv
import json
import shutil
import sys
from datetime import date, datetime, timezone

from config import DATA_DIR
from utils.data_integrity import load_dependencies, load_review_decisions

REVIEW_DIR = DATA_DIR / "review"
CSV_PATH = REVIEW_DIR / "link_decisions.csv"
MD_PATH = REVIEW_DIR / "LINK_REVIEW.md"
FIELDS = ["incident_id", "incident_service", "incident_title", "current_deployment_id",
          "current_deployment_service", "same_service_deployments",
          "decision", "new_deployment_id", "reviewer", "source", "notes"]
DECISIONS = ("replace", "none", "keep_quarantined")


def _load(name):
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


def export() -> int:
    reviews = load_review_decisions()
    deployments = _load("deployments.json")
    incidents = {i["id"]: i for i in _load("incidents.json")}
    used = {i.get("deployment_id") for i in incidents.values()}
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    rows, md = [], []
    for iid, r in sorted(reviews.items()):
        same = [d for d in deployments if d["service"] == r["incident_service"]]
        rows.append({"incident_id": iid, "incident_service": r["incident_service"],
                     "incident_title": r["incident_title"], "current_deployment_id": r["referenced_deployment_id"],
                     "current_deployment_service": r["referenced_deployment_service"],
                     "same_service_deployments": " ".join(d["deployment_id"] for d in same),
                     "decision": "", "new_deployment_id": "", "reviewer": "", "source": "", "notes": ""})
        def currently(did):
            refs = [k for k, v in incidents.items() if v.get("deployment_id") == did]
            return "already referenced by " + ", ".join(refs) if did in used else "not referenced"

        cands = "\n".join(f"  | {d['deployment_id']} | {d['time']} | {d['change']} | {currently(d['deployment_id'])} |"
                          for d in same)
        md.append(f"""### {iid} - {r['incident_title']} ({r['incident_service']})

- Recorded root cause: {r['incident_root_cause']}
- Current link: **{r['referenced_deployment_id']}** on **{r['referenced_deployment_service']}** \
("{r['referenced_deployment_change']}", {r['referenced_deployment_time']}) - a different service, and no \
documented dependency.
- Why quarantined: {r['evidence']}
- Deployments on {r['incident_service']} (for the reviewer; none is proposed):

  | deployment | time | change | currently |
  |---|---|---|---|
{cands}

- What would settle it: a change ticket, release note, postmortem or deploy log naming the deployment \
for {iid}; or the owner's confirmation that no deployment is involved.
- Decision: _pending_ (fill in `link_decisions.csv`)
""")
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    MD_PATH.write_text(f"""# Quarantined deployment links - human review

Generated {date.today().isoformat()} by `python -m scripts.link_review export` from
`backend/data/data_quality_review.json`. **{len(rows)} links need a reviewer decision.** No replacement
is suggested: the data contain nothing that identifies the correct deployment (see each entry).

How to review:
1. For each incident below, find the source that establishes its deployment (or that it had none).
2. Fill in `link_decisions.csv`: `decision` = `replace` | `none` | `keep_quarantined`;
   `new_deployment_id` for `replace`; `reviewer` and `source` for `replace` and `none`.
3. `python -m scripts.link_review check` validates the file and prints the changes.
4. `python -m scripts.link_review apply --apply` applies the valid decisions (original copied to
   `backend/data/versions/`), then re-run `python -m scripts.seed`.

`none` is applied only when the reviewer confirms it - an empty decision is never treated as `none`.

{chr(10).join(md)}""", encoding="utf-8")
    print(f"Wrote {MD_PATH} and {CSV_PATH} ({len(rows)} links, decisions empty)")
    return 0


def plan(rows: list[dict]) -> tuple[list[dict], list[str]]:
    """Valid changes and rejected rows; nothing is inferred."""
    deployments = {d["deployment_id"]: d for d in _load("deployments.json")}
    incidents = {i["id"]: i for i in _load("incidents.json")}
    reviews = load_review_decisions()
    deps = load_dependencies()
    changes, errors = [], []
    for row in rows:
        iid, decision = row.get("incident_id", "").strip(), row.get("decision", "").strip().lower()
        if not decision:
            continue                                   # pending: never defaulted
        if iid not in reviews or iid not in incidents:
            errors.append(f"{iid}: not a quarantined incident")
            continue
        if decision not in DECISIONS:
            errors.append(f"{iid}: unknown decision {decision!r} (use {', '.join(DECISIONS)})")
            continue
        if decision == "keep_quarantined":
            continue
        if not row.get("reviewer", "").strip() or not row.get("source", "").strip():
            errors.append(f"{iid}: '{decision}' needs a reviewer and a source")
            continue
        new: str | None = row.get("new_deployment_id", "").strip().upper() if decision == "replace" else None
        if decision == "replace":
            dep = deployments.get(new)
            svc = incidents[iid]["service"]
            if dep is None:
                errors.append(f"{iid}: {new or '(empty)'} is not in deployments.json")
                continue
            if dep["service"] != svc and (svc, dep["service"]) not in deps:
                errors.append(f"{iid}: {new} is on {dep['service']}, not {svc}, with no documented "
                              "dependency - it would be quarantined again")
                continue
        changes.append({"incident_id": iid, "from": incidents[iid].get("deployment_id"), "to": new,
                        "decision": decision, "reviewer": row["reviewer"].strip(), "source": row["source"].strip(),
                        "notes": row.get("notes", "").strip()})
    return changes, errors


def apply(write: bool) -> int:
    if not CSV_PATH.exists():
        raise SystemExit(f"{CSV_PATH} not found - run 'export' first")
    with open(CSV_PATH, encoding="utf-8") as f:
        changes, errors = plan(list(csv.DictReader(f)))
    for e in errors:
        print("REJECTED", e)
    for c in changes:
        print(f"CHANGE   {c['incident_id']}: deployment_id {c['from']} -> {c['to']} ({c['decision']}, "
              f"reviewer {c['reviewer']}, source {c['source']})")
    if not changes:
        print("No valid reviewer decisions to apply.")
        return 1 if errors else 0
    if not write:
        print("Dry run - pass --apply to write.")
        return 1 if errors else 0
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (DATA_DIR / "versions").mkdir(exist_ok=True)
    shutil.copy2(DATA_DIR / "incidents.json", DATA_DIR / "versions" / f"incidents_{stamp}.json")
    incidents = _load("incidents.json")
    review = _load("data_quality_review.json")
    by_change = {c["incident_id"]: c for c in changes}
    for inc in incidents:
        change = by_change.get(inc["id"])
        if change:
            if change["to"]:
                inc["deployment_id"] = change["to"]
            else:
                inc.pop("deployment_id", None)
    for rec in review["records"]:
        if rec["incident_id"] in by_change:
            c = by_change[rec["incident_id"]]
            rec["status"] = "resolved_by_reviewer"
            rec["review_history"].append({"date": date.today().isoformat(), "reviewer": c["reviewer"],
                                          "source": c["source"], "decision": c["decision"],
                                          "new_deployment_id": c["to"], "notes": c["notes"]})
    (DATA_DIR / "incidents.json").write_text(json.dumps(incidents, indent=2) + "\n", encoding="utf-8")
    (DATA_DIR / "data_quality_review.json").write_text(json.dumps(review, indent=2, ensure_ascii=False) + "\n",
                                                       encoding="utf-8")
    with open(REVIEW_DIR / "AUDIT_LOG.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"at": stamp, "action": "apply_link_decisions",
                            "original_saved_as": f"backend/data/versions/incidents_{stamp}.json",
                            "changes": changes}, ensure_ascii=False) + "\n")
    print(f"Applied {len(changes)} decision(s); original saved under backend/data/versions/. Re-run the seed.")
    return 1 if errors else 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "export":
        sys.exit(export())
    if cmd in ("check", "apply"):
        sys.exit(apply(write=cmd == "apply" and "--apply" in sys.argv))
    raise SystemExit(__doc__)
