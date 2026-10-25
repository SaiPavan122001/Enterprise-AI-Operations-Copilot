"""Propose corrected reference answers for test items whose v1 reference
asserts a QUARANTINED incident->deployment link (see
backend/data/data_quality_review.json). testset_v1 is never modified.

    python -m evals.propose_reference_corrections

Writes:
  evals/testsets/testset_v1.1-proposed.jsonl   full set, corrected references for affected items
  evals/testsets/reference_corrections_v1.1.json  per-item diff, evidence, review status
Corrections are generated from the source records only (title, recorded root
cause, the quarantined link's actual service/change); questions are unchanged.
Status is "proposed - pending human review" until a person approves them.
"""

import json
import sys

from evals.settings import repo_path
from evals.testset import read_testset


def main() -> int:
    from config import DATA_DIR

    incidents = {i["id"]: i for i in json.loads((DATA_DIR / "incidents.json").read_text(encoding="utf-8"))}
    review = {r["incident_id"]: r for r in
              json.loads((DATA_DIR / "data_quality_review.json").read_text(encoding="utf-8"))["records"]}
    items = read_testset("v1")
    corrections, out = [], []
    for item in items:
        quarantined = [e for e in item["expected_chunk_ids"]
                       if e in review and review[e]["referenced_deployment_id"] in item["reference_answer"]]
        if not quarantined:
            out.append(item)
            continue
        parts = []
        for e in item["expected_chunk_ids"]:
            i = incidents[e]
            sentence = (f"{e} ({i['service']}, \"{i['title']}\") records the root cause: {i['root_cause']}.")
            if e in review:
                r = review[e]
                sentence += (f" Its referenced deployment {r['referenced_deployment_id']} belongs to "
                             f"{r['referenced_deployment_service']} ('{r['referenced_deployment_change']}'), "
                             f"so no deployment can be verified for this incident.")
            parts.append(sentence)
        new_ref = " ".join(parts)
        corrections.append({
            "id": item["id"], "question": item["question"], "question_type": item["question_type"],
            "old_reference": item["reference_answer"], "proposed_reference": new_ref,
            "evidence": [f"data_quality_review.json: {e} quarantined ({review[e]['evidence'][:160]}...)"
                         for e in quarantined],
            "status": "proposed - pending human review",
        })
        out.append(dict(item, reference_answer=new_ref, testset_version="v1.1-proposed",
                        reference_status="proposed - pending human review"))
    with open(repo_path("evals/testsets/testset_v1.1-proposed.jsonl"), "w", encoding="utf-8") as f:
        for item in out:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    repo_path("evals/testsets/reference_corrections_v1.1.json").write_text(
        json.dumps({"base": "testset_v1.jsonl (unchanged)", "changed_items": len(corrections),
                    "questions_changed": 0, "corrections": corrections}, indent=2, ensure_ascii=False),
        encoding="utf-8")
    print(f"{len(corrections)} reference corrections proposed (questions unchanged); "
          f"wrote testset_v1.1-proposed.jsonl and reference_corrections_v1.1.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
