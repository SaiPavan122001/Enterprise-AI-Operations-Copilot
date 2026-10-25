"""How much of answer_relevancy comes from moving caveats out of the summary?

    python -m evals.relevancy_raw_summary [RUN_NAME]

Re-scores AnswerRelevancy for every model (llm) answer in a saved run using
the RAW model summary (from the captured JSON, before ``split_caveats``) plus
the same root-cause text. Policy answers keep their stored score. No answers
are regenerated.
"""

import asyncio
import json
import sys
from statistics import mean

from evals.calibration import _latest_run, _load_rows
from evals.judge import build_metrics


async def _score(metric, items):
    sem = asyncio.Semaphore(8)

    async def one(q, a):
        async with sem:
            res = await metric.ascore(user_input=q, response=a)
            return float(res.value) if res.value is not None else None

    return await asyncio.gather(*(one(q, a) for q, a in items))


def main(argv=None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    run = args[0] if args else _latest_run()
    rows = [r for r in _load_rows(run) if r.get("judge") and r["judge"].get("answer_relevancy") is not None]
    llm_rows = [r for r in rows if r["pipeline"].get("answer_source") == "llm" and r["pipeline"].get("generation")]
    items = []
    for r in llm_rows:
        raw_summary = json.loads(r["pipeline"]["generation"]["output"]).get("summary", "")
        core = r["pipeline"]["answer_core"]
        root = core.split("Root cause: ", 1)[1] if "Root cause: " in core else ""
        items.append((r["question"], f"{raw_summary}\n\nRoot cause: {root}" if root else raw_summary))
    metric = build_metrics()["answer_relevancy"]
    raw_scores = asyncio.run(_score(metric, items))
    raw_by_id = {r["id"]: s for r, s in zip(llm_rows, raw_scores)}
    final = [r["judge"]["answer_relevancy"] for r in rows]
    raw = [raw_by_id.get(r["id"], r["judge"]["answer_relevancy"]) for r in rows]
    raw = [x for x in raw if x is not None]
    print(json.dumps({
        "run": run, "n_scored": len(rows), "n_llm_rescored": len(llm_rows),
        "answer_relevancy_reported (caveats moved)": round(mean(final), 4),
        "answer_relevancy_raw_summary": round(mean(raw), 4),
        "zeros_reported": sum(1 for x in final if x == 0), "zeros_raw": sum(1 for x in raw if x == 0),
    }, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
