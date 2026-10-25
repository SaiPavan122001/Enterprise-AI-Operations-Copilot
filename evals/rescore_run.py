"""Re-judge an existing run's saved answers with the CURRENT judge
implementation, so before/after comparisons are not confounded by judge
changes. Answers are not regenerated (no pipeline, no Qdrant).

    python -m evals.rescore_run RUN_NAME

Writes <run>/summary_rejudged.json and <run>/results_rejudged.jsonl.
"""

import json
import sys

from evals.judge import FAITHFULNESS_IMPL
from evals.llm import usage
from evals.run import phase_judge, summarize
from evals.settings import load_config, repo_path


def main(argv=None) -> int:
    run_name = (argv or sys.argv[1:])[0]
    run_dir = repo_path(f"{load_config()['paths']['runs_dir']}/{run_name}/x").parent
    rows = [json.loads(line) for line in open(run_dir / "results.jsonl", encoding="utf-8")]
    for row in rows:
        for key in ("judge", "judge_reasons", "judge_claims", "refusal"):
            row.pop(key, None)
        p = row.get("pipeline") or {}
        # Runs made before answer_source existed: a model answer = captured generation.
        p.setdefault("answered", bool(p.get("generation")))
        p.setdefault("incident_ids", p.get("incident_ids") or [])
    phase_judge(rows)
    summary = summarize(rows, True)
    summary["rejudged_with"] = {"faithfulness_impl": FAITHFULNESS_IMPL,
                                "judge_model": load_config()["llm"]["judge_model"]}
    summary["judge_cost_usd"] = round(usage.cost_usd(), 4)
    (run_dir / "summary_rejudged.json").write_text(json.dumps(summary, indent=2, default=str),
                                                   encoding="utf-8")
    with open(run_dir / "results_rejudged.jsonl", "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    m = summary["metrics"]
    keys = ["faithfulness", "faithfulness_legacy_view", "faithfulness_full", "answer_relevancy",
            "context_precision", "context_recall", "answer_correctness", "correct_refusal_rate",
            "hallucination_rate", "false_refusal_rate", "hit_rate@5", "llm_fallback_rate"]
    print(json.dumps({k: m.get(k) for k in keys}, indent=1))
    print(f"judge cost: ${summary['judge_cost_usd']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
