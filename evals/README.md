# RAG evaluation harness

Offline evaluation of the copilot's retrieval and generation quality. The
harness *calls* the real retriever (`search_incidents`) and the real LangGraph
workflow (`run_investigation`); it never changes production behaviour.

## Setup

```bash
python -m venv .venv && .venv/Scripts/activate          # (Windows) or source .venv/bin/activate
pip install -r backend/requirements.txt -r evals/requirements.txt
cd backend && python -m scripts.seed && cd ..            # build the local Qdrant collection
```

Keys are read from `.env` at the repo root (never committed):
`OPENAI_API_KEY` (judge + test-set generator, and the copilot when `LLM_PROVIDER=openai`),
`GEMINI_API_KEY` (the copilot when `LLM_PROVIDER=gemini`), and `LANGFUSE_PUBLIC_KEY` /
`LANGFUSE_SECRET_KEY` / `LANGFUSE_HOST=https://jp.cloud.langfuse.com`.

### Answer-generation provider vs judge

The copilot's model and the judge are configured separately:

| Role | Where | Current value |
|---|---|---|
| Copilot answers | `.env`: `LLM_PROVIDER`, `OPENAI_MODEL` / `GEMINI_MODEL` | `openai`, `gpt-4.1-mini` |
| Judge + test-set generator | `evals/config.yaml`: `llm.judge_model`, `llm.generator_model` | `gpt-4o-mini` |

Switch the copilot back to Gemini with configuration only:

```bash
LLM_PROVIDER=gemini
GEMINI_MODEL=gemini-3.8-flash      # a model your key can use
```

Each run's name and Langfuse metadata record the provider and model. Cached answers
are keyed on (provider, model, exact prompt), so answers from one provider are never
reused for another. The 17 Gemini answers cached earlier were produced with an older
prompt, so they will not match; a Gemini run regenerates its answers. The Gemini free
tier allows about 20 requests/day per model; when the quota runs out the run stops
with exit code 3 and resumes from cache on the next attempt.

## Commands (run from the repo root)

| Step | Command |
|---|---|
| Build test set (versioned JSONL) | `python -m evals.testset build` |
| Merge SME questions | `python -m evals.testset merge-sme evals/testsets/sme_questions.jsonl` |
| Upload to Langfuse dataset | `python -m evals.testset upload` |
| Cost estimate only | `python -m evals.run --estimate-only` |
| Retrieval metrics only (free) | `python -m evals.run --retrieval-only` |
| Smoke run | `python -m evals.run --sample 20` |
| Full run | `python -m evals.run --yes` |
| CI gate | `python -m evals.run --gate --yes` (exit 1 on failure) |
| Verify a run in Langfuse (API) | `python -m evals.verify_langfuse [--run NAME]` |
| Re-derive retrieval thresholds | `python -m evals.calibrate_retrieval` |
| Evaluate the evidence match check alone | `python -m evals.evaluate_matcher [--file JSONL]` |
| End-to-end refusal policy check (no RAGAS) | `python -m evals.evaluate_policy [--file JSONL]` |
| Build a fresh matcher calibration set | `python -m evals.build_matcher_calibration` |
| Re-judge a saved run with the current judge | `python -m evals.rescore_run RUN_NAME` |
| Claim-level judge labels / agreement | `python -m evals.claim_calibration export` / `agreement --labels human` |
| Judge NLI batch-size experiment | `python -m evals.judge_batch_experiment` |
| Relevancy on raw model summaries (no caveat relocation) | `python -m evals.relevancy_raw_summary [RUN]` |
| Report tables | `python -m evals.report` |
| Calibration export / agreement | `python -m evals.calibration export` / `... agreement` |
| Unit tests | `python -m pytest evals/tests backend/tests` |

Exit codes of `evals.run`: 0 ok, 1 gate failed, 2 cost confirmation needed,
3 run stopped because the provider reported exhausted quota (completed answers
are cached; re-run the same command to resume).

Everything is configured in `evals/config.yaml`; thresholds in `evals/thresholds.yaml`.
Results go to `evals/runs/<run_name>/` (`results.jsonl` per question, `summary.json`).

## Caching and cost

* Judge and generator calls (OpenAI) are cached in `evals/.cache/llm_cache.sqlite`
  (our cache, keyed on the exact inputs) and `evals/.cache/ragas/` (RAGAS' own LLM cache).
* Copilot answers are cached keyed on (provider, model, exact prompt), so re-scoring an
  unchanged pipeline is free and a changed prompt/evidence regenerates only the affected
  questions. Use `--fresh-generation` to force new answers (e.g. to measure variance).
* Before generating, a one-call preflight fails fast on a wrong model, key or exhausted quota.
  Rows without a model answer (fallback, failure) are never judged and count toward
  `llm_fallback_rate`, which the gate requires to be 0.
* An upper-bound cost estimate is printed before every run; runs above
  `llm.confirm_above_usd` need `--yes`.

## Metric definitions

| Metric | Type | Definition |
|---|---|---|
| hit_rate@k | code | expected record in top-k |
| recall@k | code | share of expected records in top-k |
| precision@k | code | relevant / k (max = 1/k for single-record questions) |
| mrr | code | 1 / rank of first expected record (within top 10) |
| ndcg@k | code | binary-relevance nDCG |
| llm_context_hit / llm_context_precision | code | the same, on what the LLM actually received (top-5 after `MIN_RELEVANCE_SCORE`) |
| oos_context_leak_rate | code | out-of-scope questions where any incident reached the LLM |
| faithfulness | RAGAS prompts, batched NLI | share of claims in the report's **factual** sections (Summary, Impact, Evidence, Root Cause, Contributing Factors) supported by everything the LLM was given; the judge's comment lists the unsupported statements |
| faithfulness_full | same | whole report incl. remediation/preventive advice (diagnostic; advice is not expected to be in the evidence) |
| answer_relevancy | RAGAS | relevance of summary + root cause to the question |
| context_precision | RAGAS | `ContextPrecisionWithReference`: useful contexts ranked first |
| context_recall | RAGAS | reference answer claims attributable to the contexts |
| answer_correctness | RAGAS | factual + semantic match of summary + root cause vs reference |
| correct_refusal_rate | judge | out-of-scope: answer declines AND asserts no root cause |
| hallucination_rate | judge | out-of-scope: answer asserts a specific root cause |
| false_refusal_rate | judge | in-scope: answer declined although the record exists |
| permission_leaks | code | restricted records retrieved for an unauthorised user (no ACL metadata exists today → 0 tests) |

## Where to look in Langfuse

Your project is on the **JP region**: `LANGFUSE_HOST=https://jp.cloud.langfuse.com`
(`cloud.langfuse.com` rejects these keys with 401). Use the same value for the CI secret.

Verified through the API on the smoke run (UI labels below follow Langfuse's
current naming; if a label differs in your UI, the objects are the same):

* **Datasets → `rca-copilot-eval-v1`**: the 95 test items. Each holds the question
  (input), the reference answer + expected chunk IDs (expected output), and metadata
  (question_type, style, service, severity, source_doc).
* **Experiments** (Datasets → the dataset → Experiments/Runs): one entry per eval run,
  named `<embedding>_chunk-<chunking>_k<top_k>_thr<threshold>_<prompt version>_<llm>_<UTC time>[_label]`,
  e.g. `bge-small-en-v1.5_chunk-one-record-per-incident_k5_thr0.3_rca-f2b7b7f1_gemini-3.8-flash_20261023T080705Z_sample20`.
  Open it to see per-item scores and averages, and compare two runs side by side.
* **A trace** (click an experiment item, or follow `trace_url` in `results.jsonl` / REPORT.md):
  * structure: `experiment-item-run` → `experiment-item-task` → `rca-pipeline` → the observations below;
  * input/output: question, answer (summary + root cause) and the full markdown report
    (on `rca-pipeline`; the experiment item shows question → answer);
  * `retrieval.top_k` (retriever): top-10 chunks with rank, score, text and `relevant` flag;
  * `pipeline.evidence_to_llm` (retriever): incidents/deployments/runbook/log count/contexts the LLM got;
  * `rca-generation` (generation): exact prompt, model, token usage, raw answer;
  * **Scores** (28-30 per trace): `retrieval.*` (hit_rate/recall/precision/ndcg@k, mrr,
    llm_context_*, runbook_match), RAGAS `faithfulness`, `faithfulness_full`,
    `answer_relevancy`, `context_precision`, `context_recall`, `answer_correctness`,
    and `correct_refusal` / `hallucination` (out-of-scope) or `false_refusal` (in-scope),
    `pipeline.llm_fallback`, `pipeline.insufficient_evidence`. The judge's explanation
    (e.g. the list of unsupported statements for faithfulness) is the score comment.
* **Low-scoring traces**: Tracing → filter by score (e.g. `faithfulness < 0.7`) or tag
  `out_of_scope`; or the Scores view filtered by name.

### Langfuse SDK v5

The project uses the Langfuse Python SDK v5 (`langfuse>=5.0.4,<6`). Runs are created
with `Langfuse.run_experiment` on the dataset items (replacing v3 `item.run()` and
dataset-run items), and verified with the v5 read APIs (`api.experiments`,
`api.observations`, `api.scores`) by `python -m evals.verify_langfuse`.

Production traces (`backend/observability/tracing.py`) are separate: one `investigation`
trace per request with a span per stage and an `llm-generation` observation (model,
provider, token usage, attempts). They record only the question length - never the
question, prompt or answer - by design.
