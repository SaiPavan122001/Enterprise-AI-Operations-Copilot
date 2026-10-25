# RCA Copilot — Evaluation Report (round 5: remaining reliability defects)

**Date:** 2026-10-24 · **Test set:** `testset_v1.jsonl` (95: 60 single, 15 multi, 20 out-of-scope; unchanged, hash `962bf199…`) · **Copilot:** OpenAI `gpt-4.1-mini` (unchanged) · **Judge:** `gpt-4o-mini` (unchanged) · **Thresholds:** unchanged
**Defect register:** `REMAINING_DEFECTS.md` · **Audit:** `RELIABILITY_AUDIT.md` · **Previous report:** `REPORT_run20261023T152902Z.md`

| Run | Langfuse experiment | Note |
|---|---|---|
| Previous final (`…152902Z`) | `69347d73e79d0162` | round-4 baseline |
| `…073607Z_r5` | — | first verifier version: 2.7 interventions/answer, false positives, 1 false refusal → verifier redesigned |
| `…082019Z_r5-final` | `9f0aaf9b96d9dfb3` | multi-incident summary filler fired on all 15 multi answers (padding) → trigger corrected; **not used for claims below** |
| **Final (`…083052Z_r5-final2`)** | **`ba863202bc2f3e33`** — https://jp.cloud.langfuse.com/project/cmvkne3vv000lad0dbjkc0e9c/experiments/results?baseline=ba863202bc2f3e33 | 77 model + 18 policy answers; 0 fallback; Langfuse API verification passed (95/95 items; sampled traces with all expected observations, 34–35 scores) |

All three round-5 runs are reported because two intermediate results were better-looking than the final one and were rejected for the reasons given.

## 1. Gates: previous final → this round's final

| Metric | Gate | Previous | **Final** |
|---|---|---|---|
| faithfulness (validated answer) | ≥ 0.85 | 0.881 | **0.883 ✅** |
| answer_relevancy (rendered) | ≥ 0.80 | 0.808 | **0.807 ✅ (margin 0.007)** |
| answer_relevancy (raw model summary) | — | 0.643 | **0.646** |
| correct_refusal_rate | ≥ 0.90 | 0.90 (18/20) | **0.90 (18/20) ✅, at threshold** |
| ↳ 13 never-inspected out-of-scope questions | — | 11/13 | **11/13 (no change)** |
| false refusals (in-scope) | — | 3/75 | **0/75** |
| refusal precision / recall | — | 0.857 / 0.90 | **1.00 / 0.90** |
| hit_rate@5 | ≥ 0.95 | 1.00 | **1.00 ✅** |
| llm_fallback_rate | = 0 | 0 | **0 ✅** |
| multi-incident full matched recall | — | 0.867 | **1.00** |
| grounding interventions per answer | — | 0.64 | 0.83 |

**Read as "passes, at the thresholds", not a robust pass.**
- Refusal: no gain on the uninspected out-of-scope questions; D1/D2 remain (§3).
- Relevancy: passes by 0.007, and only through caveat relocation. On raw summaries it is 0.646.
- None of this round's changes was tuned on the out-of-scope questions of the test set.

**By question type (final vs previous):**

| type | n | faithfulness | relevancy rendered / raw | context recall | correctness | false refusals |
|---|---|---|---|---|---|---|
| single | 60 | 0.884 (0.888) | 0.842 / 0.657 (0.841 / 0.657) | 0.861 | 0.659 (0.661) | 0 (0) |
| **multi** | 15 | 0.877 (0.853) | **0.666 / 0.604** (0.674 / 0.585) | **0.672** (0.606) | 0.644 (0.642) | **0 (3)** |
| out-of-scope | 20 | — | — | — | — | 18/20 declined (18/20) |

**Multi-incident relevancy is not fixed (D5 PARTIAL).**
- **Gains:** the 3 "how did X affect Y" false refusals are gone, raw relevancy rose by 0.019, and context recall rose by 0.066.
- **Rendered relevancy is flat to slightly down (0.674 → 0.666).** Answers now state the relationship status explicitly, and moved causation claims are listed as hypotheses.
- **Discarded result:** the higher 0.712 in the intermediate run came from padding and is not claimed.

## 2. Held-out matcher evaluation (Phase 2)

`evals/testsets/matcher_heldout_v2.jsonl`: 46 questions in four multi-incident styles, plus terse single-incident questions and near-miss/unrelated out-of-scope questions. They were generated before the redesign, never inspected, and evaluated once before and once after the design was frozen, with aggregates only. Results: `evals/results/matcher_heldout_results.json`.

| Metric (46 held-out) | Before | After |
|---|---|---|
| in-scope full recall (31) | 0.839 | **0.935** |
| in-scope any | 0.935 | **1.000** |
| **multi-incident full recall (19)** | 0.737 | **0.895** |
| matched precision | 1.000 | 0.981 |
| out-of-scope nothing matched (15) | 1.000 | **1.000** |

**Dev comparison** (testset_v1 + calibration set; Stage A answers unchanged):
- 93/95 and 36/36 questions are identical; the 2 changes are D3 and D4, now matched.
- D4 ("the incidents in auth-service and leave-service") now matches all 5 auth/leave incidents, because the question doesn't say which ones. Precision is lower, but the result follows the question.

**Where the wording came from.** The decomposition prompt's rules ("incidents involving A and B", "specifically X and Y") and the generic-term list were written after reading the D3/D4 dev failures. The held-out result above is the only evidence that they generalise; it was obtained once, after freezing.

**Non-LLM safeguard for D1/D2: measured, not shipped.** bge similarity puts the false accepts at 0.68–0.79, above 14–43 of the 110 true matches.

## 3. Remaining failures (final run)

| Question | Trace | Cause |
|---|---|---|
| "reporting of analytics data" (out-of-scope) | `1f9e0d91…` | Stage A accepts INC-014/INC-020; arguable; no constraint applies (D1) |
| "payroll reconciliation failure" (out-of-scope) | `2ed35f6a…` | Stage A accepts INC-001/INC-015 (D2) |
| Multi-incident rendered relevancy 0.666 | — | answers state "relationship not established" plus per-incident facts; judged partially noncommittal (D5) |

## 4. Claim-support verifier (Phase 4)

Measured on labelled-by-construction claims through the production validator (`python -m evals.claim_verifier_eval`; results in `evals/results/`): 188 supported and 188 unsupported claims. The supported set includes the patterns real answers use: absence statements, multi-fact restatements and quarantine facts.

| Configuration | Precision (flagging) | Recall | False-positive rate |
|---|---|---|---|
| NLI + deterministic, stated claims (facts/impact) | **1.00** | **0.553** | **0.00** |
| NLI + deterministic, conclusions | 1.00 | 0.441 | 0.00 |
| deterministic only, stated claims | 1.00 | 0.420 | 0.00 |

Caught by category:

| Category | Caught |
|---|---|
| invented figures | 20/20 |
| deployment causation | 20/20 |
| severity swap | 20/20 |
| false verified link | 8/8 |
| service swap | 18/20 |
| cause swap | 12/20 |
| title swap | 5/20 |
| status wrong | 1/20 |
| negated cause | **0/20** |
| false absence | **0/20** |

- **Labels:** template claims; real model output is harder, so treat these numbers as an upper bound.
- **Version 1 was rejected on real answers:** 2.7 interventions per answer, mostly false positives.
- **Cost:** about 0.8 s per answer on CPU, plus an 11 s cold model load.

## 5. Data and evaluation materials (Phases 5–6), human decisions needed

- **8 quarantined links:**
  - `backend/data/review/LINK_REVIEW.md` and `link_decisions.csv`; decisions are empty and no replacement is suggested;
  - `python -m scripts.link_review check | apply --apply`.
- **Provenance:** marked `unconfirmed` in `data_quality_review.json`. Strict seeding refuses it.
- **Regeneration plan v2:** `backend/data/REGENERATION_PLAN.md`; not applied.
- **Judge calibration:**
  - blind exports from the final run in `evals/calibration/review/`: 60 claims and 100 samples, with no judge or AI labels;
  - `python -m evals.human_review validate | merge`;
  - agreement refuses to run without human labels, and the earlier zero-label agreement file was deleted.
- **17 reference corrections:**
  - `review/reference_corrections_review.csv` plus `REVIEW_GUIDE.md`;
  - `python -m evals.human_review build-v1.1` builds v1.1 only from approved rows; v1 is unchanged.

## 6. Tests, lint, CI

- **291 tests pass:** backend and eval tests, including 7 that load the local NLI model.
  - New test files: matcher requirements, multi-incident contract, claim support, data review, auth, cancellation, structured logging, human review.
- **Lint and types:** `ruff check backend evals` is clean; `mypy` (36 files) reports 0 errors, down from 67.
- **CI:** new `.github/workflows/lint.yml` (ruff, mypy, tests); `rag-eval.yml` HF cache key updated. **Not run on GitHub.** Not reproduced in a fresh venv this round: ruff, mypy and pytest ran in the existing venv.
- **Real-service checks:**
  - Langfuse API verification passed;
  - **API smoke test against the real workflow** (uvicorn, API key, live OpenAI):
    - 401 without a key;
    - `/investigate` returned 200 with a full answer;
    - `/investigate/stream` emitted all 9 stage events plus `investigation_completed`;
    - request and investigation IDs appeared in worker-thread logs.
  - **Real client disconnects** (curl `-m 2`):
    - the stream cancelled after the in-flight stage;
    - **`/investigate` did not cancel at first.** Starlette's `BaseHTTPMiddleware` (the new request-ID middleware) hid the disconnect. It was replaced with a pure ASGI middleware. After the fix, the next LLM attempt was skipped and the response was 499.
    - Regression tests now drive both endpoints through the full middleware stack with the real compiled graph.
  - a real Gemini call confirmed the 60 s timeout;
  - Gemini JSON mode is still unverified (3 timeouts).

## 7. Not production-ready

- **Gates:** refusal is at threshold (D1/D2 open); relevancy passes by 0.007 and depends on presentation; multi-incident relevancy is 0.666.
- **Claim verifier:** catches about half of unsupported claims (template estimate).
- **Human input outstanding:** no human judge calibration; 8 links, the provenance, the logs and the timestamps need the data owner.
- **Security:** the frontend API key is visible in the browser (needs SSO or a backend-for-frontend); there is no per-user identity.
- **Deployment and latency:**
  - single process only (embedded Qdrant, in-memory rate limiter);
  - latency rose: one extra LLM call per question, the NLI verifier, and 3.5 s median under 8-way concurrency with cached LLM calls.
- **Not verified for real:** cancellation was tested with curl disconnects, not a browser; Gemini JSON mode; CI on GitHub.

## 8. Files changed this round, and why

**Phase 2: matcher**
- `backend/agents/incident_matcher.py`:
  - Stage A prompt kept byte-identical;
  - new: Stage B decomposition and requirement prompts (gap-filling only);
  - per-requirement service rules, severity hard constraint, generic-requirement normalisation, fail-soft.
- `evals/build_matcher_heldout.py` (new): one-time held-out set generator.
- `evals/evaluate_matcher.py`: `--aggregate-only` flag and requirements in the output.
- `evals/results/matcher_heldout_*` (new): before/after held-out results.

**Phase 3: multi-incident answers**
- `backend/agents/rca_structured.py`:
  - multi-incident prompt block (only for 2 or more incidents);
  - `documented_links`, the inter-incident link detector and `_validate_multi`;
  - summary findings check (trigger corrected mid-round);
  - rendering of per-incident and relationship sections.
- `backend/models/evidence.py`: `per_incident_findings`, `incident_relationship`.
- `backend/agents/gemini_rca_agent.py`: passes the new fields through.

**Phase 4: claim support**
- `backend/agents/claim_verifier.py` (new): deterministic checks plus the NLI verifier; revision pinned.
- `backend/agents/rca_structured.py`:
  - `_verify_support` policy;
  - **fix:** `evidence_dates` missed ISO timestamps.
- `backend/config.py`: `CLAIM_VERIFIER*` settings.
- `evals/claim_verifier_eval.py` (new) with `evals/results/claim_verifier_eval*.json` and `evals/calibration/claim_verifier_labelled*.csv`.

**Phase 5: data**
- `backend/utils/data_integrity.py`: stale-review guard, `load_provenance`, `strict_problems`, provenance in the report.
- `backend/scripts/seed.py`: `--strict` / `SEED_STRICT`.
- `backend/scripts/link_review.py` (new): human review export, check and apply.
- `backend/data/review/` (new): `LINK_REVIEW.md` and `link_decisions.csv`, decisions empty.
- `backend/data/REGENERATION_PLAN.md` (new): not applied.
- `backend/data/data_quality_review.json`: provenance block (`unconfirmed`); records unchanged.
- `backend/api/routes.py`: provenance in `/health`.

**Phase 6: human review**
- `evals/human_review.py` (new): blind export, validate, merge, v1.1 build.
- `evals/claim_calibration.py`: agreement refuses to run without human labels.
- `evals/calibration/`:
  - re-exported from the final run (previous exports archived with a run suffix);
  - `review/` added;
  - the zero-label `claim_agreement_human.json` deleted.

**Phase 7: operations**
- `backend/utils/auth.py` (new): API keys and roles.
- `backend/api/routes.py`: auth dependencies, async `/investigate` with a disconnect watcher, a queue-based SSE stream with cancellation, investigation log context.
- `backend/app.py`:
  - pure ASGI request-ID and access-log middleware;
  - auth startup check;
  - `WEB_CONCURRENCY` guard;
  - `WWW-Authenticate` header passed through.
- `backend/utils/cancellation.py` (new).
- `backend/workflows/rca_graph.py`: stage wrapper (cancellation plus stage logging); state types.
- `backend/agents/llm_client.py`: a cancellation check before each attempt; cancellable backoff.
- `backend/utils/log_context.py` (new) and `backend/config.py`: `LOG_FORMAT`, the new installer.
- `backend/agents/gemini_rca_agent.py`: a log line per LLM call; grounding logs without claim text.
- `backend/utils/rate_limit.py`: keyed by identity; single-process limits documented.
- `frontend/src/services/api.js`: optional bearer key; 401/403 messages.
- `.env.example`, `frontend/.env.example`, `README.md`: auth, verifier and log settings; local auth instructions.

**Phase 7: lint and types**
- `ruff.toml`, `mypy.ini`, `backend/requirements-dev.txt` (new).
- `.github/workflows/lint.yml` (new).
- `rag-eval.yml`: HF cache key.
- Type and lint fixes:
  - `log_agent.py`: **fix** for the crash on a log entry with no timestamp;
  - `data_integrity.py`, `link_review.py`, `tracing.py`, `search_service.py`, `qdrant_setup.py`, `rca_graph.py`, `rca_structured.py`, `gemini_rca_agent.py`, `claim_verifier.py`: type annotations;
  - `seed.py`, `data_store.py`, `report.py`, `test_agents.py`: unused imports;
  - `verify_langfuse.py`: loop-variable binding;
  - `evals/run.py`: `raise … from None`.

**Tests**
- New: `test_matcher_requirements.py`, `test_multi_incident_contract.py`, `test_claim_support.py`, `test_data_review.py`, `test_auth.py`, `test_cancellation.py`, `test_structured_logging.py`, `evals/tests/test_human_review.py`.
- Updated:
  - `conftest.py`: deterministic verifier by default; `nli` marker;
  - `test_api.py`: a real key;
  - `test_data_integrity.py`: review fixtures name the reviewed deployment.

**Documents:** `REPORT.md`, `RELIABILITY_AUDIT.md` (round 4 archived), `REMAINING_DEFECTS.md`, `README.md`.
