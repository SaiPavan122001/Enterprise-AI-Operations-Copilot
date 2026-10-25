"""Does NLI batch size change the judge's errors? Re-verifies the labelled
claims in evals/calibration/claim_labels.csv with RAGAS' own NLI prompt at
different batch sizes and compares each with the reference label column.

    python -m evals.judge_batch_experiment [--labels assistant|human] [--sizes 1,4,8]

Each item's full production statement list is re-verified (same evidence,
same sibling statements, same order) so only the batch size differs; the
"production" row is the stored verdict from the original judge run.
"""

import argparse
import asyncio
import csv
import json
import sys

from evals.claim_calibration import DEFAULT_FILE, wilson
from evals.settings import repo_path


async def _verdicts(metric, rows, size, full_claims):
    """Verify each item's FULL production statement list (same order and
    siblings as production judging) at ``size`` statements per NLI call, and
    return verdicts for the labelled claims only."""
    by_item: dict[str, list] = {}
    for r in rows:
        by_item.setdefault(r["item_id"], []).append(r)
    out = {}
    for item_id, item_rows in by_item.items():
        ctx = item_rows[0]["evidence"]
        stmts = [c["statement"] for c in full_claims[item_id]]
        batches = [stmts[i:i + size] for i in range(0, len(stmts), size)]
        res = await asyncio.gather(*(metric._create_verdicts(b, ctx) for b in batches))
        verdicts = [bool(v.verdict) for r in res for v in r.statements]
        for r in item_rows:
            k = int(r["claim_id"].split("#")[1])
            out[r["claim_id"]] = verdicts[k] if k < len(verdicts) else None
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m evals.judge_batch_experiment")
    p.add_argument("--labels", default="assistant", choices=["assistant", "human"])
    p.add_argument("--sizes", default="1,4,8")
    args = p.parse_args(argv)
    from evals.calibration import _load_rows
    from evals.judge import build_metrics

    metric = build_metrics()["faithfulness"]
    col = f"{args.labels}_label"
    rows = [r for r in csv.DictReader(open(repo_path(DEFAULT_FILE), encoding="utf-8"))
            if r[col] in ("supported", "unsupported", "contradicted")]
    run_name = rows[0]["run_name"]
    full_claims = {r["id"]: (r.get("judge_claims") or {}).get("faithfulness") or []
                   for r in _load_rows(run_name)}
    results = {}
    production = {r["claim_id"]: r["judge_verdict"] == "supported" for r in rows}
    for size in ["production"] + [int(s) for s in args.sizes.split(",")]:
        v = production if size == "production" else asyncio.run(_verdicts(metric, rows, size, full_claims))
        truth = {r["claim_id"]: r[col] == "supported" for r in rows}
        n_sup = sum(truth.values())
        n_uns = len(truth) - n_sup
        fn = sum(1 for c, t in truth.items() if t and v[c] is False)
        fp = sum(1 for c, t in truth.items() if not t and v[c] is True)
        acc = sum(1 for c, t in truth.items() if t == v[c])
        results[size] = {"n": len(truth), "accuracy": round(acc / len(truth), 3),
                         "false_negative_rate": round(fn / n_sup, 3), "fnr_ci95": wilson(fn, n_sup),
                         "false_positive_rate": round(fp / n_uns, 3) if n_uns else None,
                         "fpr_ci95": wilson(fp, n_uns)}
        print(f"batch={size}: {json.dumps(results[size])}")
    out = repo_path(f"evals/calibration/judge_batch_experiment_{args.labels}.json")
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"labels: {args.labels} ({'PROVISIONAL AI labels' if args.labels == 'assistant' else 'human'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
