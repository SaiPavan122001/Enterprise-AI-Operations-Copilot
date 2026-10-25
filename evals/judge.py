"""Step 4: LLM-as-judge metrics.

RAGAS 0.4.x "collections" API (checked against the installed package):
    ragas.llms.llm_factory(model, client=AsyncOpenAI(), cache=DiskCacheBackend(...))
    ragas.embeddings.OpenAIEmbeddings(client=AsyncOpenAI(), model=..., cache=...)
    ragas.metrics.collections.{Faithfulness, AnswerRelevancy,
        ContextPrecisionWithReference, ContextRecall, AnswerCorrectness}
    await metric.ascore(**inputs) -> MetricResult(.value, .reason)

Two cache layers keep re-runs free: RAGAS' own DiskCacheBackend caches every
judge LLM/embedding call, and each final metric value is cached in our SQLite
cache keyed on (metric, judge model, ragas version, exact inputs).

Out-of-scope / refusal behaviour is judged separately with a small custom
prompt (RAGAS has no refusal metric).
"""

import asyncio
import logging
import math

from evals.cache import get_cache, make_key
from evals.llm import chat_json, usage
from evals.settings import load_config, repo_path

logger = logging.getLogger(__name__)

RAGAS_METRICS = ["faithfulness", "answer_relevancy", "context_precision",
                 "context_recall", "answer_correctness"]
# Diagnostics: whole report incl. advice/hypotheses, and the pre-change factual
# view (without the conclusions section) for before/after comparability.
EXTRA_METRICS = ["faithfulness_full", "faithfulness_legacy_view", "answer_relevancy_raw"]
NO_CONTEXT = "No evidence was retrieved."
# v2: same RAGAS prompts and batching as v1, but every statement and verdict is
# stored (for claim-level judge calibration). Bumping it invalidates v1 entries.
FAITHFULNESS_IMPL = "ragas-prompts-batched-nli-v2"


async def batched_faithfulness(metric, user_input: str, response: str,
                               retrieved_contexts: list[str], batch_size: int):
    """RAGAS Faithfulness with the NLI step split into batches.

    Uses RAGAS' own statement-extraction and NLI prompts (via the installed
    Faithfulness metric) but verifies statements ``batch_size`` at a time.
    Measured on this pipeline: in a single NLI call over 37 statements
    gpt-4o-mini marked 37/37 supported; in batches of 8 it marked 23/37, with
    correct verdicts on the unsupported inferences. Returns (score, reason).
    """
    statements = await metric._create_statements(user_input, response)
    if not statements:
        return None, "no statements extracted", []
    context = "\n".join(retrieved_contexts)
    batches = [statements[i:i + batch_size] for i in range(0, len(statements), batch_size)]
    results = await asyncio.gather(*(metric._create_verdicts(b, context) for b in batches))
    verdicts = [v for r in results for v in r.statements]
    unsupported = [v.statement for v in verdicts if not v.verdict]
    score = (len(verdicts) - len(unsupported)) / len(verdicts) if verdicts else None
    reason = (f"{len(verdicts) - len(unsupported)}/{len(verdicts)} statements supported"
              + (". Unsupported: " + " | ".join(unsupported) if unsupported else ""))
    claims = [{"statement": v.statement, "supported": bool(v.verdict),
               "judge_reason": getattr(v, "reason", "")} for v in verdicts]
    return score, reason[:2000], claims


def _track_usage(client, model_hint: str):
    """Wrap an AsyncOpenAI client so judge token usage feeds the cost report."""
    chat_create = client.chat.completions.create
    emb_create = client.embeddings.create

    async def chat_wrapped(*args, **kwargs):
        resp = await chat_create(*args, **kwargs)
        u = getattr(resp, "usage", None)
        if u:
            usage.add(kwargs.get("model", model_hint), u.prompt_tokens, u.completion_tokens)
        return resp

    async def emb_wrapped(*args, **kwargs):
        resp = await emb_create(*args, **kwargs)
        u = getattr(resp, "usage", None)
        if u:
            usage.add(kwargs.get("model", "embedding"), u.prompt_tokens, 0)
        return resp

    client.chat.completions.create = chat_wrapped
    client.embeddings.create = emb_wrapped
    return client


def build_metrics() -> dict:
    from openai import AsyncOpenAI
    from ragas.cache import DiskCacheBackend
    from ragas.embeddings import OpenAIEmbeddings
    from ragas.llms import llm_factory
    from ragas.metrics.collections import (
        AnswerCorrectness, AnswerRelevancy, ContextPrecisionWithReference,
        ContextRecall, Faithfulness,
    )

    cfg = load_config()["llm"]
    ragas_cache = DiskCacheBackend(cache_dir=str(repo_path("evals/.cache/ragas/x").parent))
    client = _track_usage(AsyncOpenAI(), cfg["judge_model"])
    llm = llm_factory(cfg["judge_model"], client=client, cache=ragas_cache,
                      temperature=cfg["temperature"], max_tokens=cfg["judge_max_tokens"])
    emb = OpenAIEmbeddings(client=client, model=cfg["judge_embedding_model"], cache=ragas_cache)
    faith = Faithfulness(llm=llm)
    return {
        "faithfulness": faith,
        "faithfulness_full": faith,
        "faithfulness_legacy_view": faith,
        "answer_relevancy_raw": AnswerRelevancy(llm=llm, embeddings=emb, name="answer_relevancy_raw"),
        "answer_relevancy": AnswerRelevancy(llm=llm, embeddings=emb),
        "context_precision": ContextPrecisionWithReference(llm=llm),
        "context_recall": ContextRecall(llm=llm),
        "answer_correctness": AnswerCorrectness(llm=llm, embeddings=emb),
    }


def metric_inputs(row: dict) -> dict[str, dict]:
    gcfg = load_config()["generation"]
    q, ref = row["question"], row["reference_answer"]
    ctx = row["pipeline"]["contexts"] or [NO_CONTEXT]
    prompt_ctx = row["pipeline"].get("prompt_contexts") or ctx
    p = row["pipeline"]
    views = {"full": p["answer_full"], "core": p["answer_core"],
             "factual": p.get("answer_factual") or p["answer_core"],
             "factual_legacy": p.get("answer_factual_legacy") or p.get("answer_factual") or p["answer_core"]}
    answer = views[gcfg["answer_view"]]
    return {
        "faithfulness": dict(user_input=q, response=views[gcfg["faithfulness_view"]],
                             retrieved_contexts=prompt_ctx),
        "faithfulness_full": dict(user_input=q, response=views["full"], retrieved_contexts=prompt_ctx),
        "faithfulness_legacy_view": dict(user_input=q, response=views["factual_legacy"],
                                         retrieved_contexts=prompt_ctx),
        "answer_relevancy": dict(user_input=q, response=answer),
        "answer_relevancy_raw": dict(user_input=q, response=p.get("answer_core_raw") or answer),
        "context_precision": dict(user_input=q, reference=ref, retrieved_contexts=ctx),
        "context_recall": dict(user_input=q, retrieved_contexts=ctx, reference=ref),
        "answer_correctness": dict(user_input=q, response=answer, reference=ref),
    }


def _metric_key(name: str, inputs: dict) -> str:
    import ragas

    cfg = load_config()["llm"]
    impl = FAITHFULNESS_IMPL if name.startswith("faithfulness") else "ragas"
    return make_key("ragas", name, impl, ragas.__version__, cfg["judge_model"],
                    cfg["judge_embedding_model"], cfg["judge_max_tokens"],
                    load_config()["generation"]["faithfulness_nli_batch"], inputs)


def uncached_metric_inputs(rows: list[dict], names: list[str]) -> list[tuple[str, dict]]:
    cache = get_cache()
    out = []
    for row in rows:
        for name, inputs in metric_inputs(row).items():
            if name in names and not cache.has("ragas", _metric_key(name, inputs)):
                out.append((name, inputs))
    return out


async def _score_rows(rows: list[dict], names: list[str]) -> None:
    metrics = build_metrics()
    cache = get_cache()
    sem = asyncio.Semaphore(load_config()["llm"]["max_concurrency"])
    batch = load_config()["generation"]["faithfulness_nli_batch"]

    async def one(row, name, inputs):
        key = _metric_key(name, inputs)
        hit = cache.get("ragas", key)
        if hit is None:
            async with sem:
                try:
                    claims = None
                    if name.startswith("faithfulness"):
                        value, reason, claims = await batched_faithfulness(
                            metrics[name], **inputs, batch_size=batch)
                    else:
                        res = await metrics[name].ascore(**inputs)
                        value, reason = res.value, getattr(res, "reason", None)
                    if value is not None and math.isnan(float(value)):
                        value = None
                    hit = {"value": None if value is None else float(value), "reason": reason,
                           "claims": claims}
                    cache.set("ragas", key, hit)
                except Exception as exc:  # keep going; record the failure on the row
                    logger.warning("RAGAS %s failed for %s: %s", name, row["id"], exc)
                    hit = {"value": None, "reason": f"error: {type(exc).__name__}: {exc}"[:300]}
        row.setdefault("judge", {})[name] = hit["value"]
        row.setdefault("judge_reasons", {})[name] = hit["reason"]
        if hit.get("claims") is not None:
            row.setdefault("judge_claims", {})[name] = hit["claims"]

    tasks = [one(row, name, inputs)
             for row in rows for name, inputs in metric_inputs(row).items() if name in names]
    total = len(tasks)
    done = 0
    for fut in asyncio.as_completed(tasks):
        await fut
        done += 1
        if done % 25 == 0 or done == total:
            logger.info("RAGAS progress: %d/%d metric evaluations", done, total)


def score_ragas(rows: list[dict], names: list[str] | None = None) -> None:
    names = names or (RAGAS_METRICS + EXTRA_METRICS)
    asyncio.run(_score_rows(rows, names))


# --------------------------------------------------------------------------- refusal judge

REFUSAL_PROMPT = """You grade an AI incident root-cause-analysis assistant.

QUESTION: {question}

ASSISTANT ANSWER (summary + stated root cause):
{answer}

PIPELINE EVIDENCE STRENGTH: {strength}

Decide:
- "refused": true if the assistant clearly says it cannot determine the cause / the evidence is
  insufficient or unrelated / no matching incident was found, instead of answering.
- "asserted_root_cause": true if the assistant presents a SPECIFIC root cause for the problem
  asked about as fact or as the likely cause (even if hedged as "likely").

Return JSON: {{"refused": true|false, "asserted_root_cause": true|false, "reason": "<one sentence>"}}"""


def judge_refusal(row: dict) -> dict:
    p = row["pipeline"]
    verdict = chat_json([{"role": "user", "content": REFUSAL_PROMPT.format(
        question=row["question"], answer=p["answer_core"][:4000], strength=p["evidence_strength"])}])
    refused = bool(verdict.get("refused"))
    asserted = bool(verdict.get("asserted_root_cause"))
    return {"refused": refused, "asserted_root_cause": asserted,
            "correct_refusal": 1.0 if refused and not asserted else 0.0,
            "hallucination": 1.0 if asserted else 0.0,
            "reason": verdict.get("reason")}
