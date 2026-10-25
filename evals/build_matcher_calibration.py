"""Build a FRESH calibration set for the incident match check, separate from
the evaluation test set (testset_v1 is never modified).

    python -m evals.build_matcher_calibration

Generates new questions with the same generator/filter as evals.testset but
different prompts (so none are reused from testset_v1):
  * out-of-scope near-miss / unrelated questions (filtered: no record answers them)
  * one in-scope "on-call" paraphrase per incident (filtered: identifies exactly that incident)
Questions duplicating testset_v1 are dropped. Output:
evals/testsets/matcher_calibration_v1.jsonl
"""

import json
import sys
from concurrent.futures import ThreadPoolExecutor

from evals.corpus import load_chunks
from evals.settings import load_config, repo_path
from evals.testset import (
    _finalize, _norm, gen_out_of_scope, gen_single, judge_quality, passes_filter, read_testset,
)

ONCALL_STYLE = ("Write it as a short message an on-call engineer would send in a chat while the "
                "problem is happening, describing what they observe (not the cause), in your own words.")


def main() -> int:
    cfg = load_config()
    model, judge = cfg["llm"]["generator_model"], cfg["llm"]["judge_model"]
    chunks = load_chunks()
    known = {c.chunk_id for c in chunks}
    existing = {_norm(it["question"]) for it in read_testset()}

    with ThreadPoolExecutor(8) as pool:
        cands = [r for r in pool.map(lambda c: gen_single(c, "oncall", ONCALL_STYLE, model), chunks) if r]
    cands += gen_out_of_scope(chunks, 17, model)   # different n -> different prompt than v1 (n=20)

    with ThreadPoolExecutor(8) as pool:
        verdicts = list(pool.map(lambda it: judge_quality(it, chunks, judge), cands))
    kept, seen = [], set(existing)
    for it, v in zip(cands, verdicts):
        ok, _ = passes_filter(it, v, cfg["testset"]["min_quality"], known)
        key = _norm(it["question"])
        if ok and key not in seen:
            seen.add(key)
            kept.append(_finalize(it, "matcher-cal-v1", "generated", v.get("quality")))
    out = repo_path("evals/testsets/matcher_calibration_v1.jsonl")
    with open(out, "w", encoding="utf-8") as f:
        for it in kept:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    by = {}
    for it in kept:
        by[it["question_type"]] = by.get(it["question_type"], 0) + 1
    print(f"Wrote {len(kept)} calibration questions to {out}: {by}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
