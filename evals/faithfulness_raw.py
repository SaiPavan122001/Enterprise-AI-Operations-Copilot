"""Faithfulness of the model's OWN claims, before deterministic validation.

    python -m evals.faithfulness_raw [RUN_NAME]

For every model (llm) answer in a saved run, rebuilds the factual view from
the captured JSON (summary, confirmed_facts, conclusions, impact,
contributing_factors, root-cause statement) BEFORE ``rca_structured.validate``
removed or demoted anything, and scores it with the same batched-NLI judge
and the same evidence. Compare with the reported (validated) faithfulness to
see how much of the score comes from the validator.
"""

import asyncio
import json
import sys
from statistics import mean

from evals.calibration import _latest_run, _load_rows
from evals.judge import batched_faithfulness, build_metrics
from evals.settings import load_config


def raw_view(data: dict) -> str:
    parts = []
    if data.get("summary"):
        parts.append(f"Summary: {data['summary']}")
    rc = data.get("root_cause") or {}
    if isinstance(rc, dict) and rc.get("statement"):
        parts.append(f"Root Cause: {rc['statement']}")
    for title, key in (("Impact", "impact"), ("Evidence", "confirmed_facts"),
                       ("Evidence-backed conclusions", "conclusions"),
                       ("Contributing factors", "contributing_factors")):
        items = [c.get("statement", c) if isinstance(c, dict) else str(c) for c in data.get(key) or []]
        if items:
            parts.append(f"{title}:\n" + "\n".join(f"- {x}" for x in items))
    return "\n\n".join(parts)


async def _score(metric, items, batch):
    sem = asyncio.Semaphore(8)

    async def one(q, resp, ctx):
        async with sem:
            score, _, _ = await batched_faithfulness(metric, user_input=q, response=resp,
                                                     retrieved_contexts=ctx, batch_size=batch)
            return score

    return await asyncio.gather(*(one(*i) for i in items))


def main(argv=None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    run = args[0] if args else _latest_run()
    rows = [r for r in _load_rows(run) if r.get("judge") and r["judge"].get("faithfulness") is not None
            and r["pipeline"].get("answer_source") == "llm" and r["pipeline"].get("generation")]
    items = [(r["question"], raw_view(json.loads(r["pipeline"]["generation"]["output"])),
              r["pipeline"]["prompt_contexts"]) for r in rows]
    raw = asyncio.run(_score(build_metrics()["faithfulness"], items,
                             load_config()["generation"]["faithfulness_nli_batch"]))
    validated = [r["judge"]["faithfulness"] for r in rows]
    pairs = [(v, w) for v, w in zip(validated, raw) if w is not None]
    by_type = {}
    for r, w in zip(rows, raw):
        if w is not None:
            by_type.setdefault(r["question_type"], []).append((r["judge"]["faithfulness"], w))
    print(json.dumps({
        "run": run, "n_llm_answers": len(pairs),
        "faithfulness_validated (reported view)": round(mean(v for v, _ in pairs), 4),
        "faithfulness_raw_model_claims": round(mean(w for _, w in pairs), 4),
        "by_type": {t: {"validated": round(mean(v for v, _ in xs), 4), "raw": round(mean(w for _, w in xs), 4),
                        "n": len(xs)} for t, xs in by_type.items()},
    }, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
