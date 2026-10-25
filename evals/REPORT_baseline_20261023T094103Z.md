# RCA Copilot — Evaluation Report

**Run:** `bge-small-en-v1.5_chunk-one-record-per-incident_k5_thr0.6-m0.1_rca-30aba85a_openai-gpt-4.1-mini_20261023T094103Z`
**Date:** 2026-10-23 · **Test set:** `evals/testsets/testset_v1.jsonl` (95 questions) · **Langfuse dataset:** `rca-copilot-eval-v1`
**Langfuse experiment:** `58e7193d2d91603d` — https://jp.cloud.langfuse.com/project/cmvkne3vv000lad0dbjkc0e9c/experiments/results?baseline=58e7193d2d91603d
**Results:** `evals/runs/<run>/results.jsonl` (per question) and `summary.json`

| Item | Value |
|---|---|
| Copilot answers | OpenAI `gpt-4.1-mini` (API returned `gpt-4.1-mini-2025-04-14`), `LLM_PROVIDER=openai` |
| Judge / test-set generator | OpenAI `gpt-4o-mini` (+ `text-embedding-3-small` for RAGAS relevancy/correctness) |
| Retrieval | `BAAI/bge-small-en-v1.5`, Qdrant cosine, top-5, filter floor 0.60 + margin 0.10, HIGH cut 0.75 |
| Prompt version | `rca-30aba85a` (hash of `RCA_PROMPT`) |
| Completed questions | **95 / 95** with a real model answer · 0 fallback · 0 failed · 0 skipped |
| Cost | generation ≈ $0.14 (75 new calls; 20 reused from an identical-prompt smoke run) · judge $0.57 |

## 1. Scores vs thresholds (full run, 95 questions)

| Metric | Value | Threshold | Status | n |
|---|---|---|---|---|
| hit_rate@5 | 1.000 | ≥ 0.85 | ✅ PASS | 75 in-scope |
| faithfulness | **0.756** | ≥ 0.85 | ❌ FAIL | 75 in-scope |
| answer_relevancy | 0.808 | ≥ 0.80 | ✅ PASS (narrowly) | 75 in-scope |
| correct_refusal_rate | **0.700** (14/20) | ≥ 0.90 | ❌ FAIL | 20 out-of-scope |
| permission_leaks | 0 | == 0 | ✅ PASS — *not testable: no ACL metadata exists, 0 permission tests* | 0 |
| llm_fallback_rate | 0.000 | ≤ 0.0 | ✅ PASS | 95 |

`python -m evals.run --gate` exited with **code 1**. Thresholds were not changed.

**Clean subset.** The prompt and the evidence-strength rule were changed after reading the 20 smoke-sample answers, and those 20 questions are part of the 95. On the 75 questions **not** in that sample:

| Metric | Value | n |
|---|---|---|
| faithfulness | 0.770 | 62 |
| answer_relevancy | 0.806 | 62 |
| answer_correctness | 0.584 | 62 |
| correct_refusal_rate | 0.692 (9/13) | 13 |
| false_refusal_rate | 0.032 | 62 |

Both failing gates also fail on the clean subset.

Other headline metrics: context_precision 0.795 · context_recall 0.861 · answer_correctness 0.576 ·
faithfulness_full (incl. remediation advice) 0.662 · hallucination_rate (out-of-scope) 0.300 ·
false_refusal_rate (in-scope) 0.027 (2/75) · runbook_match_rate 1.000 · MRR 0.953.

## 2. What changed and what each change did

The same 20-question stratified sample (13 in-scope, 7 out-of-scope) was run under each configuration.
All rows have real model answers unless stated.

| Metric | Gemini 3.8-flash, old retrieval (earlier smoke, 16/20 answered) | gpt-4.1-mini, **old** retrieval (ablation) | gpt-4.1-mini, new filter + evidence fix (smoke v2) | Full run (95) |
|---|---|---|---|---|
| correct_refusal_rate | 0.00 (0/5) | 0.14 (1/7) | **0.71 (5/7)** | 0.70 (14/20) |
| hallucination_rate (OOS) | 1.00 | 0.86 | 0.29 | 0.30 |
| false_refusal_rate | 0.00 | 0.00 | 0.00 | 0.03 |
| faithfulness | 0.71 | 0.74 | 0.69 | 0.76 |
| answer_relevancy | 0.75 | 0.80 | 0.82 | 0.81 |
| context_precision (RAGAS) | 0.35 | 0.42 | 0.48 | 0.80 |
| LLM context precision (code) | 0.31 | 0.31 | 0.63 | 0.68 |
| runbook_match_rate | 0.67 | 1.00* | 1.00 | 1.00 |

\*The runbook fix (top incident only) is in code, so it is active in the ablation too.
The ablation used `MIN_RELEVANCE_SCORE=0.30 RELEVANCE_MARGIN=9 STRONG_RELEVANCE_SCORE=0.45` with the new prompt.
The Gemini column used the old prompt and a different model, so it is context, not a controlled comparison.

**Read-out:**
- **Refusal behaviour.** The retrieval filter plus the evidence-strength fix moved correct refusals from 1/7 to 5/7 with the same model and prompt, and introduced no false refusals on that sample.
- **Faithfulness.** No significant change; differences of ±0.05 on 13 questions are within judge noise.
- **Runbook selection.** Now 100% consistent with the expected incident (was 67%).

## 3. Retrieval metrics (pure code)

Out-of-scope questions are excluded from ranking metrics (they have no expected chunk).

| set | n | hit@1 | hit@3 | hit@5 | hit@10 | recall@5 | recall@10 | P@1 | P@3 | P@5 | MRR | nDCG@3 | nDCG@5 | nDCG@10 | LLM ctx hit | LLM ctx precision |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| overall | 75 | 0.907 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.907 | 0.396 | 0.240 | 0.953 | 0.962 | 0.966 | 0.966 | 1.000 | 0.685 |
| single_chunk | 60 | 0.917 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.917 | 0.333 | 0.200 | 0.958 | 0.969 | 0.969 | 0.969 | 1.000 | 0.720 |
| multi_chunk | 15 | 0.867 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.867 | 0.644 | 0.400 | 0.933 | 0.933 | 0.951 | 0.951 | 1.000 | 0.542 |

P@k is bounded by |expected|/k (0.2 at k=5 for single-incident questions); recall@3 overall is 0.993.

**By service (in-scope):**

| service | n | hit@1 | hit@5 | MRR | nDCG@5 | LLM ctx precision |
|---|---|---|---|---|---|---|
| auth-service | 10 | 0.900 | 1.000 | 0.950 | 0.963 | 0.753 |
| employee-service | 10 | 1.000 | 1.000 | 1.000 | 1.000 | 0.840 |
| gateway-service | 12 | 0.750 | 1.000 | 0.875 | 0.908 | 0.519 |
| leave-service | 7 | 1.000 | 1.000 | 1.000 | 1.000 | 0.843 |
| notification-service | 9 | 0.889 | 1.000 | 0.944 | 0.959 | 0.667 |
| payroll-service | 11 | 0.909 | 1.000 | 0.955 | 0.972 | 0.639 |
| reporting-service | 10 | 1.000 | 1.000 | 1.000 | 1.000 | 0.748 |
| multiple (cross-service multi) | 6 | 0.833 | 1.000 | 0.917 | 0.928 | 0.461 |

**By severity:** Critical (22) hit@1 0.818 · High (26) 0.885 · Medium (18) 1.000 · mixed (9) 1.000; hit@5 = 1.000 for all.
Doc type: all records are `incident` (the only embedded doc type).

### Relevance filter calibration (`python -m evals.calibrate_retrieval`, seed 7)

The scores are bge-small cosine similarities, where higher means more similar, and they are compressed. Relevant incidents scored 0.65–0.94 (p05 0.70). Out-of-scope questions still reached 0.58–0.82 on their best hit (p95 0.81). **No absolute threshold can separate the two**, so the filter combines an absolute floor with a margin below the best hit. Values were picked on a dev half and checked on the held-out half:

| filter (top-5) | split | recall | precision | multi-incident recall | OOS with empty context |
|---|---|---|---|---|---|
| old: floor 0.30, no margin | all 95 | 1.000 | 0.240 | 1.000 | 0.00 |
| **new: floor 0.60, margin 0.10** | dev (47) | 1.000 | 0.673 | 1.000 | 0.11 |
| **new: floor 0.60, margin 0.10** | held-out (48) | 1.000 | 0.697 | 1.000 | 0.09 |
| rejected: floor 0.65, margin 0.07 | dev | 0.974 | 0.839 | **0.875** | 0.22 |

The stricter setting was rejected because it drops a needed incident on 1 in 8 multi-incident questions.

**HIGH cut 0.75** on the best score: on dev it keeps 97% of correct in-scope top hits and lets 11% of out-of-scope questions through; on held-out, 94% and **27%**. Score alone is a weak separator, which is why HIGH also requires the top incident's own deployment and error logs on its service.

## 4. Generation metrics (LLM-as-judge, RAGAS 0.4.3 + refusal judge)

| question_type | n | faithfulness | faithfulness_full | answer_relevancy | context_precision | context_recall | answer_correctness | correct_refusal |
|---|---|---|---|---|---|---|---|---|
| single_chunk | 60 | 0.756 | 0.670 | 0.809 | 0.869 | 0.892 | 0.569 | – |
| multi_chunk | 15 | 0.756 | 0.631 | 0.800 | 0.499 | 0.737 | 0.603 | – |
| out_of_scope | 20 | – | – | – | – | – | – | 0.700 |

| service | n | faithfulness | answer_relevancy | context_precision | context_recall | answer_correctness |
|---|---|---|---|---|---|---|
| auth-service | 10 | 0.793 | 0.765 | 0.837 | 0.850 | 0.530 |
| employee-service | 10 | 0.757 | 0.835 | 0.856 | 0.817 | 0.591 |
| gateway-service | 12 | 0.727 | 0.826 | 0.688 | 0.956 | 0.570 |
| leave-service | 7 | 0.716 | 0.852 | 1.000 | 0.881 | 0.612 |
| notification-service | 9 | 0.790 | 0.717 | 0.849 | 0.833 | 0.510 |
| payroll-service | 11 | 0.784 | 0.839 | 0.845 | 0.894 | 0.636 |
| reporting-service | 10 | 0.741 | 0.807 | 0.900 | 0.867 | 0.600 |
| multiple | 6 | 0.719 | 0.824 | 0.249 | 0.708 | 0.546 |

How the metrics are computed:
- **faithfulness** checks the report's factual sections (Summary, Impact, Evidence, Root Cause, Contributing Factors) against everything the model was given. It uses RAGAS's own statement and NLI prompts, with NLI run in batches of 8, because a single call over about 40 statements rubber-stamped them all.
- **faithfulness_full** also includes remediation and preventive advice, which is not expected to appear in the evidence.
- **Distribution:** median faithfulness is 0.77, and only 28% of answers reach 0.85 or higher. Median answer_correctness is 0.56.

**Refusal behaviour (20 out-of-scope questions):**

| style | n | correctly declined | asserted a root cause |
|---|---|---|---|
| unrelated (e.g. cloud storage, load balancers) | 6 | **6** | 0 |
| near-miss (known service, undocumented failure) | 14 | 8 | **6** |

| evidence strength assigned | declined | asserted |
|---|---|---|
| INSUFFICIENT | 2 | 0 |
| LOW | 11 | 3 |
| HIGH | 1 | 3 |

**False refusals:** 2 of 75 in-scope questions were declined. Both are caused by a data defect (§6), not by the model.

## 5. The 10 worst questions

Ranked by refusal outcome (out-of-scope) or the mean of hit@5, faithfulness, correctness, context recall and relevancy (in-scope). Each title links to its trace in Langfuse.

1. **[out_of_scope/near_miss] "What might lead to incorrect user permissions in the auth-service?"** — [trace 2b29d791…](https://jp.cloud.langfuse.com/project/cmvkne3vv000lad0dbjkc0e9c/traces/2b29d791a5c37d4ac3866c653a3e3d01)
   - Evidence strength: HIGH (top score 0.77).
   - Top-5: INC-002, INC-016, INC-008, INC-006, INC-003.
   - **Diagnosis: retrieval + evidence rating.** Auth incidents about JWT and SSO are close enough to pass the filter and the HIGH cut, and their own deployment and logs corroborate them. The model then presented the JWT mismatch as the cause of permission errors.
2. **[out_of_scope/near_miss] "What might cause a failure in processing webhook callbacks in the gateway-service?"** — [trace c33b9b5f…](https://jp.cloud.langfuse.com/project/cmvkne3vv000lad0dbjkc0e9c/traces/c33b9b5f2ff798b98a6091739ba84068)
   - Evidence strength: HIGH (top score 0.79).
   - **Diagnosis: retrieval + evidence rating.** A gateway incident about an ingress change was rated HIGH, and the answer blamed the ingress change.
3. **[out_of_scope/near_miss] "What could lead to inconsistencies in payroll deductions?"** — [trace 6d16b479…](https://jp.cloud.langfuse.com/project/cmvkne3vv000lad0dbjkc0e9c/traces/6d16b479461c0b5041a929934c982eb7)
   - Evidence strength: LOW (top score 0.73).
   - **Diagnosis: generation.** Evidence was correctly rated LOW, yet the model still named schema migration as the cause, ignoring the "inconclusive when LOW" instruction.
4. **[out_of_scope/near_miss] "What may lead to a failure in the payroll reconciliation process?"** — [trace b8f61d10…](https://jp.cloud.langfuse.com/project/cmvkne3vv000lad0dbjkc0e9c/traces/b8f61d1010fee07c2d02e58ce7222ba4)
   - Evidence strength: LOW.
   - **Diagnosis: generation.** Same pattern as #3: it repurposed the missing `salary_amount` column as the cause.
5. **[out_of_scope/near_miss] "What might cause frequent 404 errors in the gateway-service?"** — [trace 52548d98…](https://jp.cloud.langfuse.com/project/cmvkne3vv000lad0dbjkc0e9c/traces/52548d9826091978b12f49f776377f22)
   - Evidence strength: HIGH (top score 0.81).
   - **Diagnosis: retrieval + evidence rating.** Same pattern as #2.
6. **[out_of_scope/near_miss] "What might lead to differences in payroll data across regions?"** — [trace 48964a03…](https://jp.cloud.langfuse.com/project/cmvkne3vv000lad0dbjkc0e9c/traces/48964a03f82e2f809b79f83e69ec2cb6)
   - Evidence strength: LOW (top score 0.68).
   - **Diagnosis: generation.** It asserted the migration failure as the cause despite LOW evidence.
7. **[single_chunk/deployment] "What deployment is linked to the issue of the email queue growing due to a worker pod experiencing a crash loop?"** — [trace 9a0c55a9…](https://jp.cloud.langfuse.com/project/cmvkne3vv000lad0dbjkc0e9c/traces/9a0c55a9fbdae5f47db31c6099364bd9)
   - Scores: answer_relevancy 0.00, correctness 0.29.
   - **Diagnosis: data defect, not a model error.** INC-017 (notification-service) links to DEP-117, which is a *leave-service* "ETL pipeline enhancement". The model correctly said the linked deployment does not fit, but the reference answer assumes DEP-117 is the answer.
8. **[single_chunk/symptom] "Why are profile updates failing to save in the employee-service?"** — [trace d59fce84…](https://jp.cloud.langfuse.com/project/cmvkne3vv000lad0dbjkc0e9c/traces/d59fce84f9017c9e7efc895e28e351ed)
   - Scores: faithfulness 0.57, correctness 0.14.
   - **Diagnosis: generation.** Retrieval was correct (INC-013 at rank 1), but the answer adds causal claims that aren't in the evidence and diverges from the recorded root cause.
9. **[multi_chunk/cross_service] "How did the failure of the ETL job in the reporting-service (INC-014) potentially impact the database connection pool exhaustion in the employee-service (INC-013)?"** — [trace 34df1a39…](https://jp.cloud.langfuse.com/project/cmvkne3vv000lad0dbjkc0e9c/traces/34df1a3937a9cc8e746b8cf295d1182f)
   - Scores: faithfulness 0.62, correctness 0.44.
   - **Diagnosis: generation, partly a test-set issue.** Both incidents were retrieved (ranks 1 and 2). The question invites speculation about a causal link that no record supports, and the model speculates.
10. **[single_chunk/specific] "What was the root cause of the incident INC-004 regarding the notification-service's emails being delayed?"** — [trace 23b5ecd1…](https://jp.cloud.langfuse.com/project/cmvkne3vv000lad0dbjkc0e9c/traces/23b5ecd15a1e0254ccb31573a04b8e4e)
    - Scores: faithfulness 0.64, correctness 0.45.
    - **Diagnosis: generation, and possibly the judge.** Retrieval was correct (rank 1). The unsupported statements mix genuine impact inferences with restatements of the record. See §6 on judge false negatives.

**Tally of the top 10:**
- Retrieval or evidence-rating-driven: 3 (#1, #2, #5).
- Generation ignoring LOW evidence: 3 (#3, #4, #6).
- Generation adding unsupported claims: 3 (#8, #9, #10).
- Data defect: 1 (#7).
- No failures were caused by missing retrieval: hit@5 = 1.0 and the expected incident always reached the LLM.

## 6. Diagnosis of the failing gates

**correct_refusal_rate 0.70.** All 6 failures are near-miss questions. They fail in two ways:
- **(a) Evidence rated HIGH (3 cases).** A same-service incident scores at least 0.75, and every incident has its own deployment and logs, so the consistency checks pass.
- **(b) Evidence rated LOW (3 cases).** The model ignored the instruction to be inconclusive.

Refusals on unrelated topics are already 6/6. A caveat about the test set: the near-miss questions are hypothetical ("what *might* cause…"), and a human might accept "past incidents X and Y are possible causes" as helpful. The refusal judge counts any asserted cause as a failure.

**faithfulness 0.756.** This number contains both real generation errors and judge errors.
- **Real generation errors:**
  - Impact and causal inferences the evidence doesn't support, e.g. "users relying on these reports were likely impacted". The prompt now asks the model to prefix inferences with "Inference:", and it often does not.
  - Cross-incident conflation in multi-incident contexts.
- **Judge false negatives (gpt-4o-mini).** For example, in the first OpenAI smoke run, for INC-002 "users were unable to login due to a JWT signing key mismatch" was marked unsupported, although the context says `title="Users unable to login" | known root cause: JWT signing key mismatch`. The context includes up to 40 log lines, and the judge misses support that is present. How large this effect is has **not been measured yet**. That is what the calibration CSV is for (§8).

**Data defect: deployment links.** 8 of 20 incidents (INC-008, -009, -010, -011, -017, -018, -019, -020) link via `deployment_id` to a deployment on a **different service**. For example, INC-017 (notification) links to DEP-117 (leave-service, "ETL pipeline enhancement"). Effects:
- the model receives contradictory evidence;
- 2 false refusals;
- deployment-style reference answers that are not supportable;
- the HIGH "deployment consistency" check accepts these mismatched links, because it matches `deployment_id` only.

## 7. Recommendations

1. **Fix the incident→deployment data** in `backend/data/incidents.json` / `deployments.json`, or have the deployment agent and the HIGH rule also require `deployment.service == incident.service`. Then regenerate the reference answers of affected test items as a new test-set version, `v2`.
2. **Near-miss refusals.** Add an explicit match check before generation. Two options:
   - **Cheap:** a small LLM classifier ("does incident X describe the problem in the question? yes/no") that drops non-matching incidents.
   - **Free but weaker:** require the top-1 / top-2 score gap to exceed about 0.05. The in-scope median gap is 0.091; the out-of-scope median is 0.023, with a maximum of 0.072.
   - Either one should make most of the 3 HIGH-rated near-miss cases INSUFFICIENT. Validate on the held-out split.
3. **Enforce LOW/INSUFFICIENT deterministically.** When strength is LOW or INSUFFICIENT, post-process or reject a report whose Root Cause section is anything other than "Not determined". Today the prompt alone is not followed (3 of 14 LOW out-of-scope answers).
4. **Faithfulness.**
   - Trim the log context to lines from the top incident's service and time window (currently up to 40 lines across services). This reduces both model confusion and judge misses.
   - Consider structured output (JSON with `facts` / `inferences`) so inferences can be excluded from faithfulness by construction.
5. **Retrieval.** Already strong: hit@5 1.0, MRR 0.95. The bge query instruction prefix ("Represent this sentence for searching relevant passages: ") raised hit@1 from 0.907 to 0.933 in an offline check. Worth adopting together with a re-calibration of the floor and margin. Hybrid search or a reranker is not justified at 20 records.
6. **Judge calibration first.** Label the 100-row calibration CSV before tuning the prompt against faithfulness. If gpt-4o-mini's false-negative rate is high, a stronger judge (e.g. gpt-4.1) may be needed for the gate to be meaningful. Its cost is roughly 5× the judge spend, about $3 per full run.
7. **Do not change the thresholds yet.** They remain as configured. Revisit faithfulness ≥ 0.85 only after calibration quantifies judge accuracy.

## 8. Judge calibration

- `evals/calibration/calibration_samples.csv` holds **100 rows** from this run, sampled evenly across faithfulness, answer_relevancy, context_precision, context_recall, answer_correctness and correct_refusal.
- Fill in `human_label` (1 = should pass, 0 = should fail), then run `python -m evals.calibration agreement`. It reports accuracy, Cohen's κ, the judge's fail precision and recall, and Spearman correlation per metric.
- The earlier unlabeled export from the Gemini smoke run is kept as `calibration_samples_gemini_smoke_20261023.csv`.

## 9. Where to look in Langfuse (JP region)

- **Datasets → `rca-copilot-eval-v1` → Experiments:** this run, plus `…_sample20-v2` and the earlier runs. The experiment metadata holds the full configuration (provider, model, floor, margin, prompt version).
- **Open an experiment item:** the trace is `experiment-item-run` → `experiment-item-task` → `rca-pipeline`. Under it:
  - `retrieval.top_k`: the top-10 chunks with scores and relevance flags;
  - `pipeline.evidence_to_llm`: the incidents, deployments, runbook and contexts the model actually saw;
  - `rca-generation`: the exact prompt, the answer, the model and token usage.
- **Scores tab:** 28–29 scores per in-scope trace and 5 per out-of-scope trace. Judge reasons are attached as score comments.
- **Production traces:** named `investigation`, with stage spans and an `llm-generation` observation that records model, provider, attempts and usage, but never the question text.
- `python -m evals.verify_langfuse --run <name>` re-checks all of this through the API. It passed for this run.

## 10. Limitations and what is not verified

- **Small sample sizes:** 20 out-of-scope and 15 multi-incident questions. A ±1 question change moves the refusal rate by 0.05.
- **The test set was generated by gpt-4o-mini, which is also the judge.** The out-of-scope set is mostly hypothetical near-miss questions.
- **The filter and margin were tuned on half of this test set** (seed 7). Held-out figures are reported above, but both halves come from the same 20-incident corpus.
- **The prompt and the evidence-strength rule were revised after inspecting the 20-question smoke sample.** Those questions are in the full run; clean-subset figures are in §1.
- **The judge has not been calibrated against humans.** Faithfulness and correctness numbers include an unmeasured share of judge error.
- **Permission leakage is untestable:** there is no access-control metadata in the corpus.
- **Gemini after the refactor:** one real call (`LLM_PROVIDER=gemini`, `gemini-3.8-flash`) succeeded: 1 request, no retries, 191 s. No Gemini evaluation run was done; the free tier allows 20 requests/day.
- **Quota stop:** tested by simulating exhausted quota on the 3rd provider call.
  - The run stopped with exit code 3 and `complete: false`; it was not judged and `LATEST` was unchanged.
  - The re-run resumed from cache.
  - Real provider quota errors are covered by unit tests only.
- **Not exercised against real services:**
  - the GitHub Actions workflow;
  - the Langfuse UI navigation labels, which were inferred from the API objects rather than viewed.
