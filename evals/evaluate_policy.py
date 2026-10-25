"""End-to-end refusal-policy check on a question file (no RAGAS; cheap).

    python -m evals.evaluate_policy [--file JSONL]

For each question runs the real pipeline (cached) and reports:
  oos_declined      out-of-scope questions answered without a cause
                    (answer_status insufficient_evidence / out_of_scope)
  in_scope_answered in-scope questions answered from a matched incident
                    (answer_source llm with the expected incident matched)
Default file: the fresh matcher calibration set (never used for tuning).
"""

import argparse
import json
import sys

from evals.settings import repo_path


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m evals.evaluate_policy")
    p.add_argument("--file", default=str(repo_path("evals/testsets/matcher_calibration_v1.jsonl")))
    args = p.parse_args(argv)
    from evals.pipeline import install_wrappers, run_question

    install_wrappers(True)
    items = [json.loads(line) for line in open(args.file, encoding="utf-8") if line.strip()]
    oos, ins = [], []
    for it in items:
        r = run_question(it["question"])
        declined = r["answer_status"] in ("insufficient_evidence", "out_of_scope")
        if it["expected_chunk_ids"]:
            ok = (not declined) and set(it["expected_chunk_ids"]) <= set(r["incident_ids"])
            ins.append(ok)
        else:
            ok = declined
            oos.append(ok)
        if not ok:
            print(f"  MISS [{it['question_type']}] {it['question'][:90]} -> status={r['answer_status']} "
                  f"matched={r['incident_ids']} issues={r['grounding_issues'][:1]}")
    f = lambda xs: f"{sum(xs)}/{len(xs)} = {sum(xs) / len(xs):.3f}" if xs else "n/a"  # noqa: E731
    print(f"oos_declined: {f(oos)}   in_scope_answered: {f(ins)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
