"""Build a HELD-OUT set for the evidence matcher (never used for tuning).

    python -m evals.build_matcher_heldout

Generated with the same generator/filter as evals.testset, with prompts that
differ from testset_v1 and matcher_calibration_v1:
  * multi-incident questions in four styles (compare causes, X-affects-Y,
    separate impacts, "incidents on services A and B"), same- and cross-service;
  * near-miss and unrelated out-of-scope questions;
  * terse single-incident questions (ticket-title style).
Each item must pass the strict filter (the judge, seeing the whole corpus,
identifies exactly the expected incidents, or none for out-of-scope).
Output: evals/testsets/matcher_heldout_v2.jsonl by default (written once; refuses to overwrite).
    python -m evals.build_matcher_heldout --out evals/testsets/matcher_heldout_v3.jsonl --seed 2027 --oos 24
creates a further unseen set (round 6) with different pairs, records and out-of-scope questions.
"""

import argparse

import json
import random
import sys
from concurrent.futures import ThreadPoolExecutor
from itertools import combinations

from evals.corpus import load_chunks
from evals.llm import chat_json
from evals.settings import load_config, repo_path
from evals.testset import (
    SYSTEM, _finalize, _norm, gen_out_of_scope, gen_single, judge_quality, passes_filter, read_testset,
)

MULTI_STYLES = {
    "compare_causes": "Ask how the root causes of the two incidents differ.",
    "x_affects_y": ("Ask whether / how the first incident affected or related to the second "
                    "(the records may not establish any connection)."),
    "separate_impacts": "Ask what each of the two problems did to users or the service, separately.",
    "by_service": ("Ask about 'the <problem> incident on <service A> and the <problem> incident on "
                   "<service B>' using each incident's own symptom words."),
}
TERSE = "Write it as a terse ticket title an engineer would file (under 12 words), describing the symptom."
OUT = "evals/testsets/matcher_heldout_v2.jsonl"


def gen_pair(pair, style, instruction, model):
    a, b = pair
    prompt = f"""Write ONE question that needs BOTH incident records below, plus a reference answer.

RECORD A: {a.describe()}
RECORD B: {b.describe()}

STYLE: {instruction}
Rules: describe each incident specifically enough that no other incident would match; the
reference answer (2-3 sentences) uses only the records and says plainly when the records do not
establish a connection.
Return JSON: {{"question": "...", "reference_answer": "..."}}"""
    data = chat_json([{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
                     model=model, temperature=0.7)
    if not data.get("question"):
        return None
    return {"question": data["question"].strip(), "reference_answer": data.get("reference_answer", ""),
            "expected_chunk_ids": sorted([a.chunk_id, b.chunk_id]),
            "source_doc": f"backend/data/incidents.json#{a.chunk_id},{b.chunk_id}", "doc_type": "incident",
            "service": a.service if a.service == b.service else "multiple",
            "severity": a.severity if a.severity == b.severity else "mixed",
            "question_type": "multi_chunk", "question_style": style}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m evals.build_matcher_heldout")
    p.add_argument("--out", default=OUT)
    p.add_argument("--seed", type=int, default=2026)
    p.add_argument("--oos", type=int, default=13, help="out-of-scope questions to generate")
    p.add_argument("--exclude", nargs="*", default=[], help="earlier held-out files whose questions must not repeat")
    p.add_argument("--only-oos", action="store_true", help="only out-of-scope questions (generated in batches)")
    args = p.parse_args(argv)
    out_path = repo_path(args.out)
    if out_path.exists():
        raise SystemExit(f"{out_path} exists - the held-out set is written once and never regenerated")
    cfg = load_config()
    model, judge = cfg["llm"]["generator_model"], cfg["llm"]["judge_model"]
    chunks = load_chunks()
    known = {c.chunk_id for c in chunks}
    existing = {_norm(it["question"]) for it in read_testset()}
    cal = repo_path("evals/testsets/matcher_calibration_v1.jsonl")
    if cal.exists():
        existing |= {_norm(json.loads(line)["question"]) for line in open(cal, encoding="utf-8") if line.strip()}

    for prev in args.exclude:
        existing |= {_norm(json.loads(line)["question"]) for line in open(repo_path(prev), encoding="utf-8")
                     if line.strip()}
    rng = random.Random(args.seed)
    same = [p for p in combinations(chunks, 2) if p[0].service == p[1].service]
    cross = [p for p in combinations(chunks, 2) if p[0].service != p[1].service]
    rng.shuffle(same), rng.shuffle(cross)
    jobs = []
    for n, (style, instr) in enumerate(MULTI_STYLES.items() if not args.only_oos else []):
        for pair in same[n * 2:(n + 1) * 2] + cross[n * 3:(n + 1) * 3]:
            jobs.append((gen_pair, (pair, style, instr, model)))
    for c in (rng.sample(chunks, 12) if not args.only_oos else []):
        jobs.append((gen_single, (c, "terse", TERSE, model)))
    with ThreadPoolExecutor(8) as pool:
        cands = [r for r in pool.map(lambda j: j[0](*j[1]), jobs) if r]
    # Small batches: one large request truncated its JSON and lost every question.
    services = sorted({c.service for c in chunks})
    for k in range(max(1, -(-args.oos // 5))):
        focus = services[k % len(services)]
        cands += gen_out_of_scope(chunks, 5, model, variant=f"Batch {k + 1} (seed {args.seed}): include several "
                                  f"questions about {focus} and avoid generic examples.")

    with ThreadPoolExecutor(8) as pool:
        verdicts = list(pool.map(lambda it: judge_quality(it, chunks, judge), cands))
    kept, seen = [], set(existing)
    for it, v in zip(cands, verdicts):
        ok, _ = passes_filter(it, v, cfg["testset"]["min_quality"], known)
        if ok and _norm(it["question"]) not in seen:
            seen.add(_norm(it["question"]))
            kept.append(_finalize(it, out_path.stem.replace("_", "-"), "generated", v.get("quality")))
    with open(out_path, "w", encoding="utf-8") as f:
        for it in kept:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    by = {}
    for it in kept:
        k = f"{it['question_type']}/{it.get('question_style')}"
        by[k] = by.get(k, 0) + 1
    print(f"Wrote {len(kept)} held-out questions to {out_path}: {json.dumps(by)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
