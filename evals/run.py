"""End-to-end evaluation run.

    python -m evals.run                      # full test set
    python -m evals.run --sample 20          # stratified sample (smoke test)
    python -m evals.run --retrieval-only     # Step 3 only: no LLM calls, no cost
    python -m evals.run --gate               # exit 1 if any threshold in thresholds.yaml fails
    python -m evals.run --estimate-only      # print cost estimate and stop

Flow: load test set -> retrieval metrics (pure code) -> cost estimate ->
pipeline (retrieval + configured LLM) as a Langfuse experiment -> RAGAS + refusal
judge -> scores to Langfuse -> summary/results in evals/runs/<run_name>/ -> gate.
"""

import argparse
import json
import logging
import random
import sys
import threading
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from statistics import mean

from evals import langfuse_io
from evals.llm import usage
from evals.retrieval import RANKING_TYPES, aggregate, evaluate_item, retrieve
from evals.settings import load_config, load_thresholds, repo_path
from evals.testset import read_testset

logger = logging.getLogger("evals.run")

IN_SCOPE = RANKING_TYPES  # single_chunk, multi_chunk, sme: have references -> RAGAS
NO_ANSWER_TYPES = {"out_of_scope", "permission"}

# Rough per-item token budgets for the pre-run estimate (measured on this
# pipeline: the RCA prompt is ~2-3k tokens, the markdown report ~1k).
EST = {
    "generation": {"input": 3000, "output": 1800},
    "judge_per_in_scope": {"input": 30000, "output": 6000},
    "judge_refusal": {"input": 600, "output": 60},
    "embeddings_per_in_scope": 2000,
}


# --------------------------------------------------------------------------- helpers

def stratified_items(items: list[dict], n: int | None, seed: int) -> list[dict]:
    if not n or n >= len(items):
        return items
    rng = random.Random(seed)
    groups = defaultdict(list)
    for it in items:
        groups[it["question_type"]].append(it)
    for g in groups.values():
        rng.shuffle(g)
    picked = []
    while len(picked) < n:
        for key in sorted(groups):
            if groups[key] and len(picked) < n:
                picked.append(groups[key].pop())
    return picked


def estimate_cost(rows: list[dict], with_generation: bool) -> dict:
    cfg = load_config()["llm"]
    price = cfg["pricing"]
    n_in = sum(r["question_type"] in IN_SCOPE for r in rows)
    jm, em = cfg["judge_model"], cfg["judge_embedding_model"]
    from config import settings

    gm = settings.llm_model
    gen = 0.0
    if with_generation and gm in price:
        gen = len(rows) * (EST["generation"]["input"] * price[gm]["input"]
                           + EST["generation"]["output"] * price[gm]["output"]) / 1e6
    elif with_generation:
        logger.warning("No price configured for %s - generation cost not estimated", gm)
    judge = (n_in * (EST["judge_per_in_scope"]["input"] * price[jm]["input"]
                     + EST["judge_per_in_scope"]["output"] * price[jm]["output"])
             + len(rows) * (EST["judge_refusal"]["input"] * price[jm]["input"]
                            + EST["judge_refusal"]["output"] * price[jm]["output"])
             + n_in * EST["embeddings_per_in_scope"] * price.get(em, {"input": 0})["input"]) / 1e6
    return {"items": len(rows), "in_scope": n_in, "generation_model": gm,
            "generation_usd_max": round(gen, 4),
            "judge_usd_max": round(judge, 4), "total_usd_max": round(gen + judge, 4)}


def run_name_for(pcfg: dict, label: str | None) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    emb = pcfg["embedding_model"].split("/")[-1]
    name = (f"{emb}_chunk-{pcfg['chunking']}_k{pcfg['top_k']}_thr{pcfg['min_relevance_score']}"
            f"-m{pcfg['relevance_margin']}_{pcfg['prompt_version']}"
            f"_{pcfg['llm_provider']}-{pcfg['llm_model']}_{stamp}")
    return f"{name}_{label}" if label else name


def _mean(values):
    vals = [v for v in values if v is not None]
    return round(mean(vals), 4) if vals else None


# --------------------------------------------------------------------------- phases

def phase_retrieval(rows: list[dict]) -> None:
    from evals.corpus import load_chunks

    texts = {c.chunk_id: c.text for c in load_chunks()}
    cfg = load_config()["retrieval"]
    for row in rows:
        ranked = retrieve(row["question"], cfg["max_k"])
        row["retrieval"] = evaluate_item(row, ranked, cfg["k_values"])
        row["retrieval"]["ranked_detail"] = [
            {"rank": i, "chunk_id": r["id"], "score": round(r["score"], 4),
             "relevant": r["id"] in set(row["expected_chunk_ids"]), "text": texts.get(r["id"])}
            for i, r in enumerate(ranked, start=1)
        ]


class QuotaStop(Exception):
    """The provider reported exhausted quota: stop the run (resumable via cache)."""


def preflight_generation() -> None:
    """One tiny real call so a wrong model/key/quota fails clearly up front."""
    from agents.gemini_rca_agent import generate_text
    from agents.llm_client import LLMConfigError, LLMError, LLMQuotaExhaustedError
    from config import settings

    try:
        resp = generate_text("Reply with the single word OK.")
    except LLMQuotaExhaustedError as exc:
        raise SystemExit(f"Preflight: {settings.LLM_PROVIDER} quota exhausted - {exc}") from None
    except LLMConfigError as exc:
        raise SystemExit(f"Preflight: {settings.LLM_PROVIDER}:{settings.llm_model} is unavailable "
                         f"(model/key/permission) - {exc}") from None
    except LLMError as exc:
        raise SystemExit(f"Preflight: {settings.LLM_PROVIDER} call failed ({exc.kind}) - {exc}") from None
    logger.info("Preflight OK: %s answered as %s", settings.LLM_PROVIDER, resp.model)


def phase_generation(rows: list[dict], run_name: str, run_meta: dict, fresh: bool,
                     use_langfuse: bool) -> None:
    from agents.llm_client import quota_blocked
    from agents.runbook_agent import retrieve_runbook
    from config import settings
    from evals.corpus import load_chunks
    from evals.pipeline import install_wrappers, run_question

    install_wrappers(not fresh)   # once, in the main thread, before any worker starts
    chunks = {c.chunk_id: c for c in load_chunks()}
    stop = threading.Event()
    done = [0]
    lock = threading.Lock()

    def runbook_check(row, result):
        """Code-only: does the runbook chosen in production match the one the
        production selector picks when given ONLY the expected incident?
        Single-incident questions only - a cross-domain multi-incident question
        has no single correct runbook."""
        if row["question_type"] != "single_chunk" or len(row["expected_chunk_ids"]) != 1:
            return None
        oracle = retrieve_runbook(row["question"], [chunks[c] for c in row["expected_chunk_ids"]])
        expected = oracle.name if oracle else None
        return {"expected": expected, "actual": result["runbook"],
                "match": 1.0 if expected == result["runbook"] else 0.0}

    def work(row, root=None):
        if stop.is_set():
            row["skipped"] = "quota_exhausted"
            raise QuotaStop("skipped: provider quota exhausted earlier in this run")
        result = run_question(row["question"], use_cache=not fresh)
        row["pipeline"] = result
        row["runbook_check"] = runbook_check(row, result)
        langfuse_io.record_pipeline(root, row, row["retrieval"],
                                    row["retrieval"]["ranked_detail"], result)
        if result["generation_error"] == "quota_exhausted" or quota_blocked(settings.LLM_PROVIDER):
            stop.set()
        with lock:
            done[0] += 1
            if done[0] % 10 == 0 or done[0] == len(rows):
                logger.info("Pipeline progress: %d/%d", done[0], len(rows))

    workers = load_config()["generation"]["workers"]
    if use_langfuse:
        result = langfuse_io.run_experiment(rows, run_name, run_meta, work, workers)
        run_meta["experiment_id"] = result.experiment_id
        run_meta["experiment_url"] = result.experiment_url
    else:
        def local(row):
            try:
                work(row)
            except QuotaStop:
                pass

        with ThreadPoolExecutor(workers) as pool:
            list(pool.map(local, rows))
    if stop.is_set():
        raise QuotaStop(f"{settings.LLM_PROVIDER} quota exhausted during the run")


def phase_judge(rows: list[dict]) -> None:
    from evals.judge import judge_refusal, score_ragas

    # Genuine answers = validated model answers + evidence-policy answers.
    # Rows holding the evidence-only fallback (LLM failure) or skipped rows are
    # not judged: that would score the fallback, not the copilot.
    generated = [r for r in rows if r.get("pipeline") and r["pipeline"].get("answered")]
    skipped = len(rows) - len(generated)
    if skipped:
        logger.warning("%d rows have no model answer (fallback/failed/skipped) - excluded from judging",
                       skipped)
    in_scope = [r for r in generated if r["question_type"] in IN_SCOPE and r.get("reference_answer")]
    score_ragas(in_scope)
    with ThreadPoolExecutor(load_config()["llm"]["max_concurrency"]) as pool:
        for row, verdict in zip(generated, pool.map(judge_refusal, generated)):
            row["refusal"] = verdict


def row_scores(row: dict) -> tuple[dict, dict]:
    """Flat per-trace scores + comments (what gets pushed to Langfuse)."""
    scores, comments = {}, {}
    for name, v in row["retrieval"]["metrics"].items():
        scores[f"retrieval.{name}"] = v
    for name, v in (row.get("judge") or {}).items():
        scores[name] = v
        comments[name] = (row.get("judge_reasons") or {}).get(name)
    ref = row.get("refusal") or {}
    if row["question_type"] in NO_ANSWER_TYPES:
        scores["correct_refusal"] = ref.get("correct_refusal")
        scores["hallucination"] = ref.get("hallucination")
        comments["correct_refusal"] = comments["hallucination"] = ref.get("reason")
    elif ref:
        scores["false_refusal"] = 1.0 if ref.get("refused") else 0.0
        comments["false_refusal"] = ref.get("reason")
    if row.get("runbook_check"):
        scores["retrieval.runbook_match"] = row["runbook_check"]["match"]
        comments["retrieval.runbook_match"] = (
            f"expected {row['runbook_check']['expected']}, got {row['runbook_check']['actual']}")
    if row.get("pipeline"):
        p = row["pipeline"]
        scores["pipeline.llm_fallback"] = 0.0 if p.get("answered") else 1.0
        scores["pipeline.policy_answer"] = 1.0 if p.get("answer_source") == "policy" else 0.0
        scores["pipeline.grounding_issues"] = float(len(p.get("grounding_issues") or []))
        expected = set(row["expected_chunk_ids"])
        matched = set(p.get("incident_ids") or [])
        if expected:
            scores["retrieval.matched_recall"] = len(expected & matched) / len(expected)
            if matched:
                scores["retrieval.matched_precision"] = len(expected & matched) / len(matched)
        scores["pipeline.insufficient_evidence"] = (
            1.0 if row["pipeline"]["evidence_strength"] == "INSUFFICIENT" else 0.0)
    return scores, comments


def summarize(rows: list[dict], with_generation: bool) -> dict:
    retrieval = aggregate(rows, ["question_type", "service", "severity", "doc_type"])
    summary: dict = {"n_items": len(rows), "retrieval": retrieval}
    flat = dict(retrieval["overall"])
    flat.pop("n", None)

    oos = [r for r in rows if r["question_type"] == "out_of_scope"]
    flat["oos_context_leak_rate"] = _mean(r["retrieval"]["metrics"].get("oos_context_leak") for r in oos)
    perm = [r for r in rows if r.get("restricted_chunk_ids")]
    flat["permission_leaks"] = int(sum(r["retrieval"]["metrics"].get("permission_leak", 0) for r in perm))
    flat["permission_tests"] = len(perm)

    if with_generation:
        in_scope = [r for r in rows if r["question_type"] in IN_SCOPE]
        names = sorted({n for r in in_scope for n in (r.get("judge") or {})})
        for name in names:
            flat[name] = _mean((r.get("judge") or {}).get(name) for r in in_scope)
        flat["correct_refusal_rate"] = _mean((r.get("refusal") or {}).get("correct_refusal") for r in oos)
        # Refusal as a classifier (positive = declined): precision counts in-scope
        # questions that were declined; recall is the share of out-of-scope declined.
        tp = sum(1 for r in oos if (r.get("refusal") or {}).get("correct_refusal"))
        fp = sum(1 for r in rows if r["question_type"] in IN_SCOPE and (r.get("refusal") or {}).get("refused"))
        flat["refusal_precision"] = round(tp / (tp + fp), 4) if (tp + fp) else None
        flat["refusal_recall"] = round(tp / len(oos), 4) if oos else None
        flat["hallucination_rate"] = _mean((r.get("refusal") or {}).get("hallucination") for r in oos)
        flat["false_refusal_rate"] = _mean(
            (1.0 if r["refusal"]["refused"] else 0.0) for r in in_scope if r.get("refusal"))
        flat["runbook_match_rate"] = _mean(
            r["runbook_check"]["match"] for r in rows if r.get("runbook_check"))
        flat["judged_items"] = sum(1 for r in rows if r.get("refusal"))
        # Any row without a genuine answer (fallback, failure or skipped) counts.
        flat["llm_fallback_rate"] = _mean(
            0.0 if (r.get("pipeline") and r["pipeline"].get("answered")) else 1.0 for r in rows)
        flat["answer_sources"] = dict(Counter((r.get("pipeline") or {}).get("answer_source") or "skipped"
                                              for r in rows))
        flat["answer_status_by_type"] = {
            t: dict(Counter((r.get("pipeline") or {}).get("answer_status") for r in rows
                            if r["question_type"] == t))
            for t in sorted({r["question_type"] for r in rows})}
        ins_p = [r for r in in_scope if r.get("pipeline")]
        flat["matched_recall"] = _mean(
            len(set(r["expected_chunk_ids"]) & set(r["pipeline"]["incident_ids"])) / len(r["expected_chunk_ids"])
            for r in ins_p)
        flat["matched_full_recall_multi"] = _mean(
            1.0 if set(r["expected_chunk_ids"]) <= set(r["pipeline"]["incident_ids"]) else 0.0
            for r in ins_p if len(r["expected_chunk_ids"]) > 1)
        flat["oos_nothing_matched"] = _mean(
            0.0 if r["pipeline"]["incident_ids"] else 1.0 for r in oos if r.get("pipeline"))
        flat["grounding_issues_per_answer"] = _mean(
            float(len(r["pipeline"].get("grounding_issues") or [])) for r in rows if r.get("pipeline"))
        flat["generation_errors"] = dict(Counter(
            (r.get("pipeline") or {}).get("generation_error") or r.get("skipped") or "ok" for r in rows))

        by_type = {}
        for key in ("question_type", "service"):
            groups = defaultdict(list)
            for r in rows:
                groups[str(r.get(key))].append(r)
            by_type[f"by_{key}"] = {
                g: {"n": len(sub)} | {
                    name: _mean((r.get("judge") or {}).get(name) for r in sub) for name in names
                } | {"correct_refusal": _mean((r.get("refusal") or {}).get("correct_refusal")
                                              for r in sub if r["question_type"] in NO_ANSWER_TYPES)}
                for g, sub in sorted(groups.items())
            }
        summary["generation"] = by_type
    summary["metrics"] = flat
    return summary


def check_gate(metrics: dict) -> list[str]:
    failures = []
    ops = {">=": lambda a, b: a >= b, "<=": lambda a, b: a <= b, "==": lambda a, b: a == b}
    for name, rule in load_thresholds().items():
        value = metrics.get(name)
        if value is None:
            failures.append(f"{name}: missing (not computed in this run)")
        elif not ops[rule["op"]](value, rule["value"]):
            failures.append(f"{name}: {value} {rule['op']} {rule['value']} FAILED")
    return failures


def print_summary(summary: dict) -> None:
    m = summary["metrics"]
    print("\n================ EVAL SUMMARY ================")
    print(f"items: {summary['n_items']}")
    for name in sorted(m):
        print(f"  {name:32s} {m[name]}")
    print("\nThresholds:")
    failed = {f.split(":")[0] for f in check_gate(m)}
    for name, rule in load_thresholds().items():
        status = "FAIL" if name in failed else "PASS"
        print(f"  {status}  {name} = {m.get(name)}  (need {rule['op']} {rule['value']})")


# --------------------------------------------------------------------------- main

def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(name)s | %(message)s")
    for noisy in ("httpx", "httpcore", "openai", "sentence_transformers", "langfuse"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    p = argparse.ArgumentParser(prog="python -m evals.run")
    p.add_argument("--sample", type=int, help="stratified sample size (by question_type)")
    p.add_argument("--types", help="comma-separated question types to include")
    p.add_argument("--retrieval-only", action="store_true")
    p.add_argument("--gate", action="store_true", help="exit 1 if thresholds fail")
    p.add_argument("--no-langfuse", action="store_true")
    p.add_argument("--fresh-generation", action="store_true", help="bypass the generation response cache")
    p.add_argument("--estimate-only", action="store_true")
    p.add_argument("--yes", action="store_true", help="skip the cost confirmation")
    p.add_argument("--label", help="suffix for the run name")
    p.add_argument("--testset-file", help="JSONL test set other than the configured version (e.g. an unseen "
                   "held-out set); requires --no-langfuse (the Langfuse dataset mirrors testset_v1)")
    args = p.parse_args(argv)

    cfg = load_config()
    if args.testset_file:
        if not args.no_langfuse:
            raise SystemExit("--testset-file requires --no-langfuse")
        with open(args.testset_file, encoding="utf-8") as f:
            items = [json.loads(line) for line in f if line.strip()]
    else:
        items = read_testset()
    if args.types:
        wanted = set(args.types.split(","))
        items = [it for it in items if it["question_type"] in wanted]
    rows = [dict(it) for it in stratified_items(items, args.sample, cfg["testset"]["seed"])]
    with_generation = not args.retrieval_only

    from evals.pipeline import pipeline_config

    pcfg = pipeline_config()
    run_name = run_name_for(pcfg, args.label or (f"sample{args.sample}" if args.sample else None))
    logger.info("Run %s on %d items", run_name, len(rows))

    estimate = estimate_cost(rows, with_generation)
    print(f"\nEstimated upper-bound cost (before cache hits): {json.dumps(estimate)}")
    if args.estimate_only:
        return 0
    if (with_generation and estimate["total_usd_max"] > cfg["llm"]["confirm_above_usd"]
            and not args.yes):
        print(f"Estimated cost exceeds ${cfg['llm']['confirm_above_usd']} - re-run with --yes to proceed.")
        return 2

    phase_retrieval(rows)
    logger.info("Retrieval metrics computed")

    use_langfuse = with_generation and not args.no_langfuse and langfuse_io.get_client() is not None
    incomplete = None
    if with_generation:
        if not pcfg["llm_configured"]:
            raise SystemExit(f"{pcfg['llm_provider'].upper()}_API_KEY is not set - the copilot would "
                             "only return fallback reports. Set it, or use --retrieval-only.")
        preflight_generation()
        run_meta = {**pcfg, "testset_version": cfg["testset"]["version"]}
        try:
            phase_generation(rows, run_name, run_meta, args.fresh_generation, use_langfuse)
        except QuotaStop as exc:
            incomplete = str(exc)
            logger.error("STOPPED: %s. Completed answers are cached; re-run the same command "
                         "to resume once quota is available.", exc)
        from evals.pipeline import gen_usage

        logger.info("%s calls: %d (%d served from eval cache)", pcfg["llm_provider"],
                    gen_usage.calls, gen_usage.cached)
        if incomplete is None:
            phase_judge(rows)

    summary = summarize(rows, with_generation and incomplete is None)
    summary["run_name"] = run_name
    summary["complete"] = incomplete is None
    summary["incomplete_reason"] = incomplete
    summary["pipeline_config"] = pcfg
    summary["judge_usage"] = usage.by_model
    summary["judge_cost_usd"] = round(usage.cost_usd(), 4)
    if with_generation:
        from evals.pipeline import gen_usage

        summary["generation_usage"] = {k: v for k, v in vars(gen_usage).items() if not k.startswith("_")}
        summary["langfuse_experiment"] = {k: run_meta.get(k) for k in ("experiment_id", "experiment_url")}

    if use_langfuse:
        for row in rows:
            scores, comments = row_scores(row) if row.get("pipeline") else ({}, {})
            langfuse_io.push_scores(row.get("trace_id"), scores, comments)
            row["trace_url"] = langfuse_io.trace_url(row.get("trace_id"))
        langfuse_io.flush()

    out_dir = repo_path(f"{cfg['paths']['runs_dir']}/{run_name}/x").parent
    with open(out_dir / "results.jsonl", "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    with open(out_dir / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)
    if incomplete is None:
        (out_dir.parent / "LATEST").write_text(run_name, encoding="utf-8")

    print_summary(summary)
    print(f"\nJudge cost this run: ${summary['judge_cost_usd']}  |  results: {out_dir}")
    if incomplete is not None:
        print(f"\nRUN INCOMPLETE: {incomplete}. Not judged; LATEST not updated. Re-run to resume.")
        return 3

    if args.gate:
        failures = check_gate(summary["metrics"])
        if failures:
            print("\nREGRESSION GATE FAILED:\n  " + "\n  ".join(failures))
            return 1
        print("\nRegression gate passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
