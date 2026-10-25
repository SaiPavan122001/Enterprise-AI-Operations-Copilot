"""Standalone evaluation of the incident match check (agents/incident_matcher.py)
on the real retriever output, before it is trusted in the workflow.

    python -m evals.evaluate_matcher [--exclude-run RUN_DIR_SUFFIX] [--seed 7]

For every test question: retrieve top-5 -> production relevance filter ->
match check (configured LLM, cached). Reports, per dev / held-out split
(same seeded split as calibrate_retrieval) and overall:
  in_scope_full_recall   expected incidents all marked same_problem
  in_scope_any           at least one expected incident matched
  matched_precision      matched incidents that are expected
  multi_full_recall      multi-incident questions with every incident matched
  oos_nothing_matched    out-of-scope questions with no match (desired)
Questions from an excluded run (e.g. the inspected smoke sample) are dropped.
"""

import argparse
import json
import random
import sys

from evals.settings import load_config, repo_path
from evals.testset import read_testset


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m evals.evaluate_matcher")
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--exclude-run", default="sample20-v2",
                   help="suffix of a run dir whose questions were inspected (excluded)")
    p.add_argument("--out", default=None)
    p.add_argument("--file", default=None, help="JSONL test file (default: testset_v1)")
    p.add_argument("--aggregate-only", action="store_true",
                   help="aggregates only (held-out sets: misses are not inspected)")
    args = p.parse_args(argv)

    from agents.incident_agent import incident_agent
    from evals.pipeline import install_wrappers

    install_wrappers(True)
    if args.file:
        with open(args.file, encoding="utf-8") as f:
            items = [json.loads(line) for line in f if line.strip()]
    else:
        items = read_testset()
    runs = repo_path(load_config()["paths"]["runs_dir"] + "/x").parent
    excluded = set()
    if args.exclude_run:
        for d in runs.iterdir():
            if d.name.endswith(args.exclude_run) and (d / "results.jsonl").exists():
                excluded |= {json.loads(line)["id"] for line in open(d / "results.jsonl", encoding="utf-8")}
    ids = sorted(it["id"] for it in items)
    random.Random(args.seed).shuffle(ids)
    dev = set(ids[: len(ids) // 2])

    from security.access import system_principal
    from workflows.rca_graph import incident_matching_node

    principal = system_principal("eval-harness")

    rows = []
    for it in items:
        cands = incident_agent(it["question"])["incidents"]
        # The production node: named-ID candidates + LLM verdicts + deterministic rules.
        state = incident_matching_node({"question": it["question"], "incidents": list(cands),
                                        "_principal": principal})
        m = state["match"]
        cands = state["incidents"] + state.get("related_incidents", [])
        rows.append({"id": it["id"], "type": it["question_type"], "style": it.get("question_style"),
                     "question": it["question"], "expected": it["expected_chunk_ids"],
                     "candidates": [c.incident_id for c in cands], "matched": m.matched_ids,
                     "scope": m.question_scope, "error": m.error, "assessments": m.assessments,
                     "requirements": m.requirements,
                     "split": "dev" if it["id"] in dev else "held_out", "excluded": it["id"] in excluded})

    def stats(sub):
        ins = [r for r in sub if r["expected"]]
        oos = [r for r in sub if not r["expected"]]
        multi = [r for r in ins if len(r["expected"]) > 1]
        f = lambda xs: round(sum(xs) / len(xs), 3) if xs else None  # noqa: E731
        prec = [len(set(r["matched"]) & set(r["expected"])) / len(r["matched"]) for r in ins if r["matched"]]
        return {"n_in": len(ins), "n_oos": len(oos),
                "in_scope_full_recall": f([set(r["expected"]) <= set(r["matched"]) for r in ins]),
                "in_scope_any": f([bool(set(r["expected"]) & set(r["matched"])) for r in ins]),
                "matched_precision": f(prec),
                "multi_full_recall": f([set(r["expected"]) <= set(r["matched"]) for r in multi]),
                "oos_nothing_matched": f([not r["matched"] for r in oos]),
                "errors": sum(1 for r in sub if r["error"])}

    kept = [r for r in rows if not r["excluded"]]
    print(f"excluded (inspected) questions: {len(rows) - len(kept)}")
    for label, sub in (("dev", [r for r in kept if r["split"] == "dev"]),
                       ("held_out", [r for r in kept if r["split"] == "held_out"]),
                       ("all_not_excluded", kept), ("all_95", rows)):
        print(f"{label:17s} {json.dumps(stats(sub))}")
    if args.aggregate_only:
        return 0
    print("\nMisses (in-scope not fully matched / out-of-scope matched):")
    for r in rows:
        bad_in = r["expected"] and not set(r["expected"]) <= set(r["matched"])
        bad_oos = not r["expected"] and r["matched"]
        if bad_in or bad_oos:
            reasons = {a["incident_id"]: (a["verdict"], a["reason"][:90]) for a in r["assessments"]}
            print(f"  [{r['type']}/{r['style']}{' EXCL' if r['excluded'] else ''}] {r['question'][:95]}\n"
                  f"     expected={r['expected']} candidates={r['candidates']} matched={r['matched']} "
                  f"scope={r['scope']}\n     verdicts={reasons}")
    out = args.out or repo_path("evals/runs/matcher_eval.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2)
    print(f"\nSaved {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
