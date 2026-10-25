"""Verify through the Langfuse API (v5 read endpoints) that an eval run was
recorded correctly: the experiment exists, its items are linked to the
dataset, and sampled traces contain the prompt, retrieved evidence, answer
and scores.

    python -m evals.verify_langfuse [--run RUN_NAME] [--sample 5]

Exit code 1 if any check fails. Langfuse ingestion is asynchronous, so the
script polls for a few minutes before failing.
"""

import argparse
import json
import random
import sys
import time
from datetime import datetime, timedelta, timezone

from evals.calibration import _latest_run, _load_rows
from evals.langfuse_io import get_client, with_retry
from evals.settings import load_config, repo_path

EXPECTED_OBSERVATIONS = {"retrieval.top_k", "pipeline.evidence_to_llm"}


def _poll(fn, ok, attempts=12, wait=15):
    result = None
    for _ in range(attempts):
        result = fn()
        if ok(result):
            return result
        time.sleep(wait)
    return result


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m evals.verify_langfuse")
    p.add_argument("--run")
    p.add_argument("--sample", type=int, default=5)
    args = p.parse_args(argv)

    run_name = args.run or _latest_run()
    run_dir = repo_path(f"{load_config()['paths']['runs_dir']}/{run_name}/x").parent
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    rows = [r for r in _load_rows(run_name) if r.get("trace_id")]
    lf = get_client()
    since = datetime.now(timezone.utc) - timedelta(days=7)
    failures: list[str] = []

    # 1. Experiment exists, is linked to the dataset, and has all items.
    exp_id = (summary.get("langfuse_experiment") or {}).get("experiment_id")
    exps = _poll(lambda: with_retry(lf.api.experiments.list, from_start_time=since, name=run_name),
                 lambda r: bool(r.data))
    exp = next((e for e in exps.data if e.id == exp_id), exps.data[0] if exps.data else None)
    if exp is None:
        failures.append(f"experiment '{run_name}' not found")
    else:
        # Attribute access (pydantic models; .dict() would use camelCase aliases).
        dataset_id, item_count = getattr(exp, "dataset_id", None), getattr(exp, "item_count", None)
        print(f"experiment: id={exp.id} name={exp.name} dataset_id={dataset_id} item_count={item_count}")
        if not dataset_id:
            failures.append("experiment is not linked to a dataset")
        items = _poll(lambda: with_retry(lf.api.experiments.list_items, from_start_time=since,
                                         experiment_id=exp.id, limit=100),
                      lambda r: len(r.data) >= len(rows))
        print(f"experiment items via API: {len(items.data)} (expected {len(rows)})")
        if len(items.data) < len(rows):
            failures.append(f"experiment has {len(items.data)} items, expected {len(rows)}")

    # 2. Sampled traces: observations with prompt/evidence/answer, and scores.
    sample = random.Random(0).sample(rows, min(args.sample, len(rows)))
    for row in sample:
        tid = row["trace_id"]
        obs = _poll(lambda tid=tid: with_retry(lf.api.observations.get_many, trace_id=tid,
                                       fields="core,basic,io,model,usage", limit=50),
                    lambda r: EXPECTED_OBSERVATIONS <= {o.name for o in r.data})
        by_name = {o.name: o for o in obs.data}
        missing = EXPECTED_OBSERVATIONS - set(by_name)
        gen = by_name.get("rca-generation")
        expected_scores = 1  # at least the retrieval scores
        scores = _poll(lambda tid=tid: with_retry(lf.api.scores.get_many, trace_id=tid, limit=100),
                       lambda r, n=expected_scores: len(r.data) >= n)
        names = sorted({s.name for s in scores.data})
        problems = []
        if missing:
            problems.append(f"missing observations {sorted(missing)}")
        if row["pipeline"].get("candidate_ids") and "incident-match" not in by_name:
            problems.append("no incident-match observation")
        if row["pipeline"].get("answer_source") == "policy" and "rca-policy-answer" not in by_name:
            problems.append("no rca-policy-answer observation")
        if row["pipeline"].get("generation"):
            if gen is None:
                problems.append("no rca-generation observation")
            elif ("USER QUESTION" not in str(gen.input) or row["question"] not in str(gen.input)
                  or "root_cause" not in str(gen.output) or not gen.usage_details):
                problems.append("rca-generation lacks prompt/answer/usage")
        evid = by_name.get("pipeline.evidence_to_llm")
        if evid is not None and "contexts" not in str(evid.output):
            problems.append("evidence observation lacks contexts")
        if not any(n.startswith("retrieval.") for n in names):
            problems.append("no retrieval scores")
        if row.get("judge") and not any(n in names for n in ("faithfulness", "answer_correctness")):
            problems.append("no RAGAS scores")
        status = "OK " if not problems else "BAD"
        print(f"{status} trace {tid} [{row['question_type']}] obs={sorted(by_name)} "
              f"scores={len(scores.data)} {('; '.join(problems))}")
        if problems:
            failures.append(f"trace {tid}: {'; '.join(problems)}")

    if failures:
        print("\nVERIFICATION FAILED:\n  " + "\n  ".join(failures))
        return 1
    print("\nLangfuse verification passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
