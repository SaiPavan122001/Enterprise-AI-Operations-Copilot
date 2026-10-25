# RCA Copilot — Evaluation Report

## Round 8 (2026-10-25): NeMo Guardrails and prompt-injection protection

**Scope:** guardrails and prompt injection only. The thresholds and the judge are unchanged. Full audit, method and limits: `PROMPT_INJECTION_AUDIT.md`.

**NeMo's role.** NeMo 0.24.1 orchestrates three rail configs of custom actions. Its own LLM is a stub (0 calls per request) and none of its built-in rails are used. Its native retrieval rail does not fire in rails-only mode (proven by a probe).

**Verified gaps fixed:**
- an action crash inside NeMo was read as "passed" (fail-open);
- a quarantined deployment link leaked raw record text into the prompt;
- the output rail allowed links planted in records;
- a `GUARDRAILS_MODE` typo disabled the rails;
- the self-check failed open on errors;
- no rail timeout;
- cancellation was swallowed;
- four record fields skipped the retrieval rail;
- the self-check delimiter was injectable;
- no normalisation of encoded text;
- prompts had no untrusted-data fences;
- MCP output was not neutralised;
- no check for leaked internal instructions.

**New suite** (`injection_v1`, 400 rows): public deepset rows, rows written by `gpt-4o-mini` (not the copilot model), encoded variants and translations. The 191-row held-out split was frozen before any fix.

**Full-path attacks succeeding, guardrails ON, live:**
- held-out: **2/22 → 1/22**. This is one case: the quarantined link.
- dev: 5/18 → 1/18 (in-sample).

The samples are small, and a re-run moves single cases. The remaining success is a question that dictates a non-link token.

**Detection (held-out):**
- deterministic layer: 9 → 24 of 118 (encoded attacks 0 → 15 of 25), benign false-positive rate unchanged at 1/61;
- with the self-check: 79 → 80 of 118, false-positive rate unchanged at 3/61;
- latency unchanged (~1.1 s for the input rail).

**RAG gates** (RCA and matcher calls fresh; self-check verdicts likely replayed from the cache):
- testset_v1 **passes** every gate (faithfulness 0.876, relevancy 0.804, refusal 0.90; Langfuse run `…051804Z_r8-injection`).
- Unseen relevancy **still fails** (0.766; r7 0.780).
- 0 questions were blocked by a guardrail. 3/75 in-scope answers were judged refusals (r7: 0/75); see the audit §5.3.

**Tests:**
- Full suite: **504 pass + 1 strict xfail** (a known false positive, kept).
- `test_prompt_injection.py` holds 56 new tests (55 pass + the xfail). They include API-path tests on `/investigate` and SSE, which run through the new rail thread pool with `engine=nemo`.
- 2 round-7 tests were changed deliberately: the fail-closed self-check, and the link-rule wording.
- ruff and mypy are clean (54 files).

**Not complete protection.** Remaining limits: no system/user role split, multilingual and paraphrased attacks rely on the self-check, noisy generated labels, and no human red team. See the audit §6.

---

## Round 7 (2026-10-24): security capabilities - RBAC, PII, NeMo Guardrails, tool authorization, approvals

**Scope:** five security capabilities were added. Answer generation, the judge, the retrieval settings and the evaluation thresholds are unchanged. Full design, evidence and limits are in `GUARDRAILS_AUDIT.md` (§R7). The round-6 report follows below and is also archived as `REPORT_round6.md`.

| Run | Set | Langfuse |
|---|---|---|
| `…143427Z_r7-final` / `…143722Z_unseen-r7` | first round-7 version | `06ff0ea2b8ed6f21` |
| **`…144550Z_r7-final2`** | testset_v1 (95), **final** | **`ce9f6618fbc52701`** (API verification passed, 95/95) |
| **`…144824Z_unseen-r7b`** | 90 unseen (round-6 set), **final** | local |

### RAG gates with every round-7 control on (thresholds unchanged)

Controls on: auth principal, PII, all three rails with the LLM self-check, and the output rail.

| Metric | Gate | Round 6 testset_v1 | **Round 7 testset_v1** | Round 6 unseen | **Round 7 unseen** |
|---|---|---|---|---|---|
| faithfulness | ≥ 0.85 | 0.883 | **0.883** | 0.871 | **0.871** |
| answer_relevancy | ≥ 0.80 | 0.807 | **0.807** | 0.780 ❌ | **0.780 ❌** |
| correct refusal | ≥ 0.90 | 0.90 | **0.90** | 0.971 | **0.971** |
| false refusals (in-scope) | — | 0/75 | **0/75** | 0/22 | **0/22** |
| llm_fallback_rate | = 0 | 0 | **0** | 0 | **0** |
| hit_rate@5 | ≥ 0.95 | 1.0 | **1.0** | 1.0 | **1.0** |
| multi-incident relevancy | — | 0.662 | 0.662 | 0.732 | 0.732 |
| median latency per question (eval, 8 concurrent) | — | single 3.1 s · multi 5.8 s | **single 5.7 s · multi 10.1 s** | single 2.7 s · multi 4.0 s | **single 4.7 s · multi 8.1 s** |

**Quality is unchanged and latency rose by roughly 2–4 s.** The main cost is the input rail's LLM self-check (median 1.05 s on its own), plus Presidio and NeMo overhead under concurrency. The relevancy gate still fails on unseen questions; that is pre-existing (round 6), not caused by this round.

**Regression found and fixed.** The first round-7 unseen run showed an `llm_fallback_rate` of 0.044 and 62/68 refusals.
- **Cause:** 4 benign out-of-scope questions were declined by the input rail (a "password reset" pattern match, and LLM self-check blocks with category "none").
- **Harness gap:** `evals/pipeline.py` did not count `answer_source="guardrail"` as an answer.
- **Fixes:** the pattern exclusions, a rule that an LLM block must name an attack category, and the harness accounting. All are regression-tested, and the 4 questions were inspected to make the fix.

### Security evaluation (live model; `evals/results/security_eval_r7*.json`)

| | Attacks succeeding (of 11) | In-scope questions blocked (of 97) | Out-of-scope questions blocked (of 88) | Input-rail latency |
|---|---|---|---|---|
| Guardrails off | 6 | — | — | — |
| Deterministic rails only | 1 | 0 | 1 | 17 ms |
| **Default (with LLM self-check)** | **0** | **0** | **0** | **1.05 s** |

The attacks were written by the developer: a small set, not a red team. **Injection protection is not complete.**

### Tests, checks and the end-to-end flow

- **Tests:** 449 pass (backend + evals). 123 are new: RBAC 28, tools and approvals 30, PII 26, guardrails 39.
- **Static checks:** ruff clean; mypy 0 errors in 54 files.
- **Frontend:** the production build succeeds. The frontend ESLint configuration was already broken before this round and was not fixed.
- **End-to-end via the Vite `/api` proxy:** 19/19 checks behaved as specified (`GUARDRAILS_AUDIT.md` §R7.6). Not a clicked-through UI test.

### Dependencies

- Added: `nemoguardrails` 0.24.1, `presidio-analyzer` 2.2.364, `spacy` 3.8.16 with `en_core_web_sm` 3.8.0.
- Upgraded: `pydantic` 2.10.4 → 2.14.1 (required by the new packages); `numpy` 2.5.4 → 2.4.6 (spaCy constraint); `mcp` 1.12.4 → 1.30.0, because 1.12.4 breaks on pydantic 2.14.
- All 326 pre-existing tests pass on the new versions.

### Not safe for public deployment

The remaining blockers are listed in `GUARDRAILS_AUDIT.md` §R7.4–R7.5:
- in-process session, rate-limit and approval stores;
- no SSO/MFA;
- `/search` and request-size limits;
- public docs and health endpoints;
- no independent injection red team.

---

## Round 6 — Evaluation Report (round 6: verifier recall, refusal / multi-incident quality, human review)

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
