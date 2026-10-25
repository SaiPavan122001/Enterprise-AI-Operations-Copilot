"""Calibrate the incident relevance filter (MIN_RELEVANCE_SCORE / RELEVANCE_MARGIN)
and the HIGH evidence cut (STRONG_RELEVANCE_SCORE). Pure retrieval, no LLM.

    python -m evals.calibrate_retrieval [--seed 7]

The test set is split 50/50 (seeded) into dev and held-out halves. The grid is
evaluated on dev; the chosen setting is then reported on held-out data so the
choice is not just fit to the questions it is judged on.

Metrics on the top-5 the incident agent sees, after the filter:
  recall        share of expected incidents kept            (must stay ~1.0)
  precision     share of kept incidents that are expected   (noise removed)
  oos_empty     out-of-scope questions with nothing kept
  multi_recall  recall on multi-incident questions          (must stay ~1.0)
"""

import argparse
import json
import random
import sys

from evals.retrieval import retrieve
from evals.testset import read_testset

FLOORS = [0.30, 0.60, 0.65, 0.68, 0.70, 0.72, 0.75]
MARGINS = [0.03, 0.05, 0.07, 0.10, 0.15, None]
HIGH_CUTS = [0.72, 0.75, 0.78, 0.80]


def kept(ranked, floor, margin, k=5):
    from agents.incident_agent import select_relevant

    return select_relevant([(r["id"], r["score"]) for r in ranked[:k]],
                           min_score=floor, margin=9.0 if margin is None else margin)


def evaluate(items, results, floor, margin):
    rec, prec, oos, multi = [], [], [], []
    for it in items:
        k = set(kept(results[it["id"]], floor, margin))
        e = set(it["expected_chunk_ids"])
        if e:
            rec.append(len(e & k) / len(e))
            prec.append(len(e & k) / len(k) if k else 0.0)
            if len(e) > 1:
                multi.append(len(e & k) / len(e))
        else:
            oos.append(1.0 if not k else 0.0)
    m = lambda xs: round(sum(xs) / len(xs), 3) if xs else None  # noqa: E731
    return {"recall": m(rec), "precision": m(prec), "oos_empty": m(oos), "multi_recall": m(multi),
            "n_in_scope": len(rec), "n_oos": len(oos)}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m evals.calibrate_retrieval")
    p.add_argument("--seed", type=int, default=7)
    args = p.parse_args(argv)

    from config import settings

    items = read_testset()
    results = {it["id"]: retrieve(it["question"], 10) for it in items}
    ids = sorted(results)
    random.Random(args.seed).shuffle(ids)
    dev_ids = set(ids[: len(ids) // 2])
    dev = [it for it in items if it["id"] in dev_ids]
    held = [it for it in items if it["id"] not in dev_ids]

    print(f"Split seed={args.seed}: dev={len(dev)} held-out={len(held)}\n")
    print("DEV grid (floor, margin) -> recall / precision / oos_empty / multi_recall")
    for floor in FLOORS:
        for margin in MARGINS:
            r = evaluate(dev, results, floor, margin)
            print(f"  floor={floor:.2f} margin={str(margin):5s} -> {r['recall']} / {r['precision']} "
                  f"/ {r['oos_empty']} / {r['multi_recall']}")

    cur = (settings.MIN_RELEVANCE_SCORE, settings.RELEVANCE_MARGIN)
    print(f"\nConfigured filter floor={cur[0]} margin={cur[1]}:")
    for label, subset in (("dev", dev), ("held-out", held), ("all", items)):
        print(f"  {label:9s} {json.dumps(evaluate(subset, results, *cur))}")
    print(f"  baseline (floor=0.30, no margin) all: {json.dumps(evaluate(items, results, 0.30, None))}")

    print("\nHIGH-strength cut on best score (correct top-1 in-scope vs out-of-scope top-1):")
    for label, subset in (("dev", dev), ("held-out", held)):
        ins = [results[i["id"]][0]["score"] for i in subset
               if i["expected_chunk_ids"] and results[i["id"]][0]["id"] in i["expected_chunk_ids"]]
        oo = [results[i["id"]][0]["score"] for i in subset if not i["expected_chunk_ids"]]
        for cut in HIGH_CUTS:
            print(f"  {label:9s} cut={cut:.2f}: in-scope >= cut {sum(s >= cut for s in ins) / len(ins):.2f}"
                  f" | out-of-scope >= cut {sum(s >= cut for s in oo) / len(oo):.2f}")
    print(f"\nConfigured STRONG_RELEVANCE_SCORE={settings.STRONG_RELEVANCE_SCORE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
