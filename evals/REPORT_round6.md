# RCA Copilot — Evaluation Report (round 6: verifier recall, refusal / multi-incident quality, human review)

**Date:** 2026-10-24 · **Test set:** `testset_v1.jsonl` (95; unchanged, sha256 `962bf199…`) · **Copilot:** `gpt-4.1-mini` · **Judge:** `gpt-4o-mini` · **Thresholds:** unchanged
**Round-5 baseline:** `REPORT_run20261024T083052Z_round5.md` (run `…083052Z_r5-final2`, Langfuse `ba863202bc2f3e33`)
**Defects:** `REMAINING_DEFECTS.md` · **Audit:** `RELIABILITY_AUDIT.md` · **Human input:** `HUMAN_INPUT_NEEDED.md`

## Runs

| Run | Set | Use |
|---|---|---|
| `…091823Z_unseen-r5baseline` | 90 unseen questions | round-5 code on unseen data, **before any round-6 change** |
| `…100231Z_r6-final` | testset_v1, Langfuse `4fbadccbbeae4f49` | first round-6 version |
| `…100551Z_unseen-r6` | 90 unseen | first round-6 version: **regression** (3 false refusals), see §3 |
| **`…101849Z_r6-final2`** | **testset_v1, Langfuse `7f8d5a8e45b10191`** (API verification passed, 95/95) | **final** |
| **`…102120Z_unseen-r6b`** | **90 unseen** | **final**. The 3 regressed questions were inspected to fix them, so 3 of these 90 are no longer unseen |

**Unseen sets were generated before any round-6 rule was written:**

| File | Contents |
|---|---|
| `testsets/matcher_heldout_v3.jsonl` | 17 multi-incident + 5 single-incident |
| `testsets/matcher_heldout_v3_oos*.jsonl` | 68 out-of-scope (23 near-miss), de-duplicated against every earlier set |
| `testsets/unseen_r6_v1.jsonl` | the two combined (90 questions) |
| `testsets/claim_verifier_heldout_v1.jsonl` | 356 LLM-reworded labelled claims |

## 1. Gates and key metrics

| Metric | Gate | Round 5 (testset_v1) | **Round 6 (testset_v1)** | Unseen, round-5 code | **Unseen, round-6 code** |
|---|---|---|---|---|---|
| faithfulness | ≥ 0.85 | 0.883 | **0.883** | 0.863 | **0.871** |
| answer_relevancy (rendered) | ≥ 0.80 | 0.807 | **0.807** | 0.763 ❌ | **0.780 ❌** |
| answer_relevancy (raw summary) | — | 0.646 | 0.646 | 0.642 | 0.643 |
| correct refusal | ≥ 0.90 | 0.90 (18/20) | **0.90 (18/20)** | 0.971 (66/68) | **0.971 (66/68)** |
| false refusals (in-scope) | — | 0/75 | **0/75** | 0/22 | **0/22** (3/22 in the first round-6 version) |
| refusal precision / recall | — | 1.00 / 0.90 | 1.00 / 0.90 | 1.00 / 0.971 | 1.00 / 0.971 |
| multi-incident relevancy (rendered / raw) | — | 0.666 / 0.604 | 0.662 / 0.604 | 0.710 / 0.720 | **0.732 / 0.722** |
| multi-incident full matched recall | — | 1.00 | 1.00 | 0.824 | 0.824 |
| hit_rate@5 · fallback | ≥ 0.95 · = 0 | 1.0 · 0 | 1.0 · 0 | 1.0 · 0 | 1.0 · 0 |
| calibration agreement (human) | — | not computable | **not computable: 0 human labels** | — | — |

**How to read it:**

- **testset_v1:** the gates pass, but every metric is within noise of round 5. Answers are cached, so only the validation changed.
- **Unseen: the relevancy gate fails, before and after this round** (0.763 → 0.780). The testset_v1 pass does not generalise. This is the most important result of the round, and no threshold was changed.
- **Regressions and why:**
  - testset_v1 multi-incident relevancy 0.666 → 0.662 and faithfulness 0.8831 → 0.8828: within judge noise. The answers were served from cache and only post-validation changed.
  - The first round-6 version made 3 unseen in-scope answers look like refusals (§3). This was fixed.

## 2. Claim-support verifier (task 1)

**Why recall was 0.553.** All verifier misses came from three classes the round-5 design deliberately left unchecked:
- negations and absence statements, which were not sent to NLI because NLI judged true absence statements "contradicted";
- facts NLI scored below the 0.9 contradiction threshold: swapped titles and causes, wrong status;
- deployment causation phrased without the regex's cue words.

Measured on unseen rewordings, round 5 was even weaker than the templates suggested: recall **0.394**, not 0.553.

**What changed.** New deterministic checks compare each claim with the record it cites:
- a wrong status ("still unresolved");
- a negated recorded cause ("was not X", "X was not the cause", "not caused by X", "did not result from X");
- false absence ("no recorded root cause", "root cause is unknown", "no deployment linked", "no log line corroborates" when the record says otherwise);
- another incident's recorded cause or title stated for the cited incident;
- wider deployment-causation cues ("responsible for", "stemmed from", "root cause was a … deployment").

Each rule was then narrowed after measured false positives on real answers and dev data:
- negated attributions ("cannot be attributed to");
- link phrasing ("… and is linked to deployment");
- vocabulary from cited deployments ("ingress configuration change");
- recorded titles used as labels;
- a cause containing the word "missing";
- statements about **another, unmatched** incident's missing evidence (found in the unseen run).

| Set (stated-claim policy) | Precision | Recall | FPR |
|---|---|---|---|
| dev templates, round 5 | 1.000 | 0.553 | 0.000 |
| **dev templates, round 6** | **1.000** | **0.989** | **0.000** |
| unseen rewordings, round 5 | 0.987 | 0.394 | 0.006 |
| **unseen rewordings, round 6** | **0.993** | **0.723** | **0.006** |
| unseen, deterministic only, round 6 | 1.000 | 0.660 | 0.000 |

**Per class on unseen rewordings, before → after:**

| Class | Before | After |
|---|---|---|
| negated cause | 0/20 | 15/20 |
| false absence | 0/20 | 8/20 |
| wrong status | 0/20 | 19/20 |
| title swap | 4/20 | 15/20 |
| cause swap | 4/20 | 11/20 |
| deployment causation | 3/20 | 5/20 |

- **Real answers:** 596 claims that survived round-5 validation were replayed through the new rules; **1** new flag remained, and the assistant judged it a correct catch. This is not a human label.
- **Limits:**
  - The dev-to-unseen gap (0.989 vs 0.723) shows the rules partly fit template wording.
  - Deployment causation and false absence stay weak on reworded text.
  - The unseen claim set was scored 3 times on successive versions, aggregates only. Its rewrites are LLM-made, so a few labels may not hold.

## 3. Refusal and multi-incident quality (task 2)

- **D1/D2 (two out-of-scope false accepts) are still open.** A second, independently framed LLM check of every accepted match was tried on dev and **rejected**:
  - it called "payroll reconciliation" the *same* as "payroll generation";
  - it described the asked problem using the record's own words;
  - it rejected an exact-title in-scope question.

  On unseen data, out-of-scope rejection is already 0.956 at the matcher and 0.971 end to end, so D1/D2 look like hard edge cases, not a systematic leak. No rule was tuned to them.
- **Coverage:** when a multi-incident question asks about something no retrieved record covers, that part is now recorded in the evidence notes the model sees and in Unknowns.
  - **Not** appended to the summary. The first version did this, and on unseen questions it produced 3 false refusals: decomposition sometimes invents "parts" (one answer covered every asked incident yet got two "no record describes …" sentences).
- **Relationship questions:** when a connection is asked about and is not established, and the summary does not say so, the relationship statement is appended. No causal link is ever stated as fact (unchanged from round 5).
- **Matcher:** unchanged from round 5.
  - held-out v2 multi-incident full recall 0.895;
  - unseen v3 multi-incident full recall 0.824 (3/17 missed);
  - unseen out-of-scope rejection 0.956;
  - dev 1.00 / 0.90.

## 4. Human calibration and data review (task 3)

**Blocked on human input.** Nothing has been entered: claims 0/60, judge samples 0/100, reference corrections 0/17, links 0/8, provenance unconfirmed. Exact steps are in `HUMAN_INPUT_NEEDED.md`.

Prepared or added this round:
- an **audit trail**:
  - `human_review merge` copies each calibration CSV to `*.pre-merge-<time>.csv` and appends to `review/AUDIT_LOG.jsonl`;
  - `build-v1.1` logs the approved IDs and reviewers;
  - `link_review apply` writes `backend/data/review/AUDIT_LOG.jsonl` alongside the versioned `incidents.json` copy;
- tests showing a merge with no labels changes nothing.

Agreement refuses to run without human labels. AI provisional labels stay in their own file and are not reported as calibration. No reference, link or label was changed.

## 5. Tests and checks

- **326 tests pass:** backend and eval, including the NLI-marked tests. The 35 new ones are:
  - verifier record-contradiction, true-statement and real-answer false-positive cases;
  - deployment-causation phrasings;
  - multi-incident coverage and relationship statements;
  - audit trail.
- `ruff`: clean · `mypy`: 0 errors · Langfuse verification of the final run passed.
- Unchanged and not re-verified this round: auth, cancellation, logging; Gemini JSON mode; GitHub CI.

## 6. Files changed this round

- `backend/agents/claim_verifier.py`: record-contradiction rules (status, negated cause, false absence, other incident's cause or title), `states_absence`, and the cited-record vocabulary.
- `backend/agents/rca_structured.py`:
  - wider deployment-causation cues, the root-cause-is-deployment pattern and title stripping;
  - more negated-link phrasings;
  - `_state_insufficient_evidence` (relationship statement only).
- `backend/agents/incident_matcher.py`: `MatchResult.uncovered` (parts no record addresses). The second-check Stage C was added and then removed.
- `backend/workflows/rca_graph.py`: uncovered parts become evidence notes.
- `backend/utils/data_store.py`: `get_incidents()`.
- `evals/build_matcher_heldout.py`: `--out/--seed/--oos/--exclude/--only-oos`; batched out-of-scope generation.
- `evals/testset.py`: optional batch variant in `gen_out_of_scope`, because the response cache repeated identical batches.
- `evals/run.py`: `--testset-file`, local only.
- `evals/build_verifier_heldout.py` (new).
- `evals/claim_verifier_eval.py`: `--file`, `--tag`, `link_table`.
- `evals/human_review.py`, `backend/scripts/link_review.py`: audit log and archives.
- Tests:
  - `test_claim_support.py`, `test_matching_and_claims.py`, `test_multi_incident_contract.py`, `test_grounding_and_refusal.py` (fixture corrected: it gave INC-001 another incident's cause);
  - `evals/tests/test_human_review.py`.
- New data and results:
  - `evals/testsets/matcher_heldout_v3*.jsonl`, `unseen_r6_v1.jsonl`, `claim_verifier_heldout_v1.jsonl`;
  - `evals/results/*r6*`, `*r5baseline*`;
  - `evals/HUMAN_INPUT_NEEDED.md`.

## 7. Not production-ready

- **Gates:** relevancy fails on unseen questions (0.780); on testset_v1 it passes by 0.007, and only through caveat relocation.
- **D1/D2** remain; refusal on testset_v1 is at the threshold.
- **Claim verifier:** catches about 72% of unsupported claims on reworded text, and is weak on deployment causation and false absence.
- **Human input:** no human judge calibration; every data and reference decision is still pending.
- **Carried over from round 5:**
  - single-process only;
  - the frontend key is visible in the browser;
  - added latency (decomposition call + NLI);
  - Gemini JSON mode unverified;
  - CI not run on GitHub.
