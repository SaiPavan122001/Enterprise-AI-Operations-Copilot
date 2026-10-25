"""Langfuse integration for evals - Langfuse Python SDK v5 (OpenTelemetry-based).

APIs used (checked against the installed 5.0.4 package and the official
v3->v4 / v4->v5 migration guides):
  Langfuse(public_key=, secret_key=, base_url=)
  Langfuse.create_dataset / create_dataset_item / get_dataset      (unchanged)
  Langfuse.run_experiment(name=, run_name=, data=[DatasetItem], task=, max_concurrency=, metadata=)
      replaces v3 DatasetItemClient.run(); items stay linked to the dataset
  span.start_observation(as_type="retriever"|"generation"|"chain", ...), span.update(...)
      (v3 start_span / update_trace are removed)
  propagate_attributes(tags=, metadata=dict[str, str])               (trace-level attributes)
  Langfuse.create_score(trace_id=, name=, value=, comment=)          (unchanged, batched)
  Langfuse.get_trace_url(trace_id=)
  Reads for verification: api.experiments.list / list_items, api.observations.get_many,
  api.scores.get_many (v3 legacy read endpoints are not used).

Each eval trace contains: the question (input), the answer (output), a
retriever observation with the ranked top-k chunks (+ text and scores), a
retriever observation with the exact evidence given to the LLM, and a
generation observation with the exact prompt, model, token usage and answer.
"""

import asyncio
import hashlib
import json
import logging
import os
import threading
import time
from typing import Callable

from evals.settings import load_config

logger = logging.getLogger(__name__)

_client = None
_api_lock = threading.Lock()


def with_retry(fn, *args, attempts: int = 8, **kwargs):
    """Call a Langfuse public-API method, waiting out 429 rate limits.

    Langfuse Cloud allows ~100 public-API requests/min; uploads make one
    request per item. Traces and scores go through the batched OTel/score
    exporters and are not affected.
    """
    for attempt in range(1, attempts + 1):
        try:
            with _api_lock:   # serialise so parallel workers don't stampede the limit
                return fn(*args, **kwargs)
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            if status != 429 or attempt == attempts:
                raise
            body = getattr(exc, "body", None) or {}
            wait = (body.get("details") or {}).get("retryAfterSeconds", 30) if isinstance(body, dict) else 30
            logger.info("Langfuse rate limit hit - waiting %ss (attempt %d/%d)", wait + 1, attempt, attempts)
            time.sleep(float(wait) + 1)


def get_client():
    """Return the Langfuse client, or None if keys are not configured."""
    global _client
    if _client is not None:
        return _client
    if not (os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY")):
        logger.warning("Langfuse keys not set - results stay local only")
        return None
    from langfuse import Langfuse

    _client = Langfuse(
        public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
        secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
        base_url=os.getenv("LANGFUSE_HOST"),
    )
    if not _client.auth_check():
        raise RuntimeError("Langfuse auth_check failed - check LANGFUSE_* keys and host "
                           "(this project is on https://jp.cloud.langfuse.com)")
    return _client


def dataset_name(version: str | None = None) -> str:
    cfg = load_config()
    return f"{cfg['langfuse']['dataset_prefix']}-{version or cfg['testset']['version']}"


def dataset_item_id(item: dict) -> str:
    # Item IDs are project-unique in Langfuse, so namespace by test-set version.
    return f"{item['testset_version']}-{item['id']}"


def _item_payload(item: dict) -> dict:
    return {
        "input": {"question": item["question"]},
        "expected_output": {"reference_answer": item["reference_answer"],
                            "expected_chunk_ids": item["expected_chunk_ids"]},
        "metadata": {k: item.get(k) for k in (
            "id", "question_type", "question_style", "service", "severity",
            "doc_type", "source_doc", "restricted_chunk_ids", "origin")},
    }


def _fingerprint(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def upload_dataset(items: list[dict]) -> str:
    """Create the dataset if missing and upsert only new/changed items, so
    re-running (e.g. in CI) does not re-send or duplicate anything."""
    lf = get_client()
    if lf is None:
        raise RuntimeError("Langfuse keys are required to upload the dataset")
    version = items[0]["testset_version"]
    name = dataset_name(version)
    try:
        existing = {it.id: it for it in with_retry(lf.get_dataset, name).items}
    except Exception as exc:
        if getattr(exc, "status_code", None) not in (404, None):
            raise
        existing = {}
        with_retry(
            lf.create_dataset, name=name,
            description=f"RCA copilot eval test set {version} (evals/testsets/testset_{version}.jsonl)",
            metadata={"testset_version": version, "items": len(items)},
        )
    sent = 0
    for item in items:
        payload = _item_payload(item)
        current = existing.get(dataset_item_id(item))
        if current is not None and _fingerprint({
                "input": current.input, "expected_output": current.expected_output,
                "metadata": current.metadata}) == _fingerprint(payload):
            continue
        with_retry(lf.create_dataset_item, dataset_name=name, id=dataset_item_id(item), **payload)
        sent += 1
    lf.flush()
    logger.info("Langfuse dataset '%s': %d items in test set, %d already up to date, %d upserted",
                name, len(items), len(items) - sent, sent)
    return name


def dataset_items_by_id(version: str | None = None) -> dict:
    lf = get_client()
    if lf is None:
        return {}
    dataset = with_retry(lf.get_dataset, dataset_name(version))
    return {it.id: it for it in dataset.items}


def run_experiment(rows: list[dict], run_name: str, metadata: dict, work: Callable[[dict, object], None],
                   max_concurrency: int):
    """Run ``work(row, root_span)`` for every row as one Langfuse experiment on
    the dataset. ``work`` runs in a worker thread (asyncio.to_thread copies the
    OTel context, so its observations nest under the experiment item trace)."""
    lf = get_client()
    ds_items = dataset_items_by_id()
    rows_by_ds_id = {dataset_item_id(r): r for r in rows}
    missing = [k for k in rows_by_ds_id if k not in ds_items]
    if missing:
        raise SystemExit(f"{len(missing)} items are not in the Langfuse dataset - "
                         "run `python -m evals.testset upload` first")

    def run_one(row):
        with lf.start_as_current_observation(name="rca-pipeline", as_type="chain",
                                             input={"question": row["question"]}) as root:
            row["trace_id"] = root.trace_id
            work(row, root)

    async def task(*, item, **kwargs):
        row = rows_by_ds_id[item.id]
        await asyncio.to_thread(run_one, row)
        p = row.get("pipeline") or {}
        return {"answer": p.get("answer_core"), "evidence_strength": p.get("evidence_strength"),
                "generation_error": p.get("generation_error")}

    result = lf.run_experiment(
        name=run_name, run_name=run_name,
        description="RCA copilot eval (evals/run.py)",
        data=[ds_items[k] for k in rows_by_ds_id],
        task=task, max_concurrency=max_concurrency,
        metadata={k: str(v) for k, v in metadata.items()},
    )
    lf.flush()
    logger.info("Langfuse experiment '%s' (id=%s): %d/%d items completed. %s",
                run_name, result.experiment_id, len(result.item_results), len(rows),
                result.experiment_url or "")
    return result


def record_pipeline(root, item: dict, retrieval: dict, ranked_detail: list[dict], result: dict) -> None:
    """Attach retrieval + generation observations under the item's root span."""
    if root is None:
        return
    from langfuse import propagate_attributes

    root.update(
        output={"answer": result["answer_core"], "report_markdown": result["answer_full"]},
        metadata={
            "item_id": item["id"], "question_type": item["question_type"],
            "question_style": item.get("question_style"), "service": item.get("service"),
            "expected_chunk_ids": item["expected_chunk_ids"],
            "reference_answer": item["reference_answer"],
            "evidence_strength": result["evidence_strength"],
            "confidence": result["confidence"],
            "answer_status": result.get("answer_status"),
            "answer_source": result.get("answer_source"),
            "generation_error": result.get("generation_error"),
            "grounding_issues": result.get("grounding_issues"),
            "missing_evidence": result.get("missing_evidence"),
            "contradictions": result.get("contradictions"),
        },
    )
    # Trace-level tags/metadata must be short strings in v5.
    with propagate_attributes(tags=["eval", item["question_type"]],
                              metadata={"item_id": item["id"],
                                        "question_type": item["question_type"]}):
        ranked = root.start_observation(
            name="retrieval.top_k", as_type="retriever",
            input={"query": item["question"], "k": len(ranked_detail)},
            output=ranked_detail,
            metadata={"expected_chunk_ids": item["expected_chunk_ids"],
                      "note": "eval-only call to search_incidents(limit=max_k) for ranking metrics"},
        )
        ranked.end()

        match = result.get("match_generation")
        if match:
            m = root.start_observation(
                name="incident-match", as_type="generation",
                model=match["model"], input=match["prompt"], output=match["output"],
                usage_details={"input": match["usage"].get("input", 0),
                               "output": match["usage"].get("output", 0)},
                metadata={"matched": result.get("incident_ids"),
                          "not_matched": result.get("related_incident_ids"),
                          "from_eval_cache": match["cached"]},
            )
            m.end()

        evidence = root.start_observation(
            name="pipeline.evidence_to_llm", as_type="retriever",
            input={"question": item["question"]},
            output={"matched_incident_ids": result["incident_ids"],
                    "related_not_matched": result.get("related_incident_ids"),
                    "incident_scores": result["incident_scores"],
                    "deployment_ids": result["deployment_ids"], "link_notes": result.get("link_notes"),
                    "runbook": result["runbook"],
                    "log_count": result["log_count"], "contexts": result["contexts"]},
            metadata={"retrieval_errors": result["retrieval_errors"],
                      "llm_context_ids": retrieval.get("llm_context_ids")},
        )
        evidence.end()

        gen = result.get("generation")
        if gen:
            g = root.start_observation(
                name="rca-generation", as_type="generation",
                model=gen["model"], input=gen["prompt"], output=gen["output"],
                usage_details={"input": gen["usage"].get("input", 0),
                               "output": gen["usage"].get("output", 0)},
                metadata={"provider": gen.get("provider"), "from_eval_cache": gen["cached"],
                          "latency_ms": gen.get("latency_ms"), "attempts": gen.get("attempts")},
            )
            g.end()
        elif result.get("answer_source") == "policy":
            note = root.start_observation(
                name="rca-policy-answer", as_type="span",
                status_message=f"Evidence policy answer ({result.get('answer_status')}): no matched incident; "
                               "no cause requested from the model",
                output=result["answer_full"],
            )
            note.end()
        else:
            note = root.start_observation(
                name="rca-generation.failed", as_type="span", level="ERROR",
                status_message=(f"No model answer ({result.get('generation_error')}): "
                                f"{result.get('generation_error_message') or ''}")[:500],
                output=result["answer_full"],
            )
            note.end()


def push_scores(trace_id: str, scores: dict[str, float], comments: dict[str, str] | None = None) -> None:
    lf = get_client()
    if lf is None or not trace_id:
        return
    comments = comments or {}
    for name, value in scores.items():
        if value is None:
            continue
        lf.create_score(trace_id=trace_id, name=name, value=float(value),
                        data_type="NUMERIC", comment=(comments.get(name) or None))


def trace_url(trace_id: str | None) -> str | None:
    lf = get_client()
    if lf is None or not trace_id:
        return None
    try:
        return lf.get_trace_url(trace_id=trace_id)
    except Exception:
        return None


def flush() -> None:
    if _client is not None:
        _client.flush()
