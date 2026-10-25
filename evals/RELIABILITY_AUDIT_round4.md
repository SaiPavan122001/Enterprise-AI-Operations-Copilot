# Reliability Audit — Enterprise AI Operations Copilot

**Date:** 2026-10-23 · **Branch:** `main`. All work is uncommitted; nothing was committed, pushed or deployed.

**Source of truth.** The repo has no `CLAUDE.md`, `PROJECT_STATUS.md`, `PHASE_PLAN.md` or `DECISIONS.md`. The source of truth is the code, the tests and the run artifacts in `evals/runs/`.

**Architecture as found:**
- FastAPI backend, LangGraph workflow, React frontend.
- Knowledge layer: JSON files (`backend/data/`) plus an **embedded Qdrant** collection (20 points, one per incident).
- **There is no PostgreSQL or any other relational database.** "Relational joins" are the validated in-code joins.

**Timing.** The inspection (Phase 1) was done before any change. This document was written afterwards, so its **Status** column shows the **post-change** state; the "Known failure" and "Change made" columns record what was found and fixed.

**End-to-end traces** (final run, experiment `69347d73e79d0162`):
- **Single-incident**, "Why are users unable to login to the auth-service?" (trace `92e919fe…`):
  - retrieval: INC-002, INC-016, INC-008; match: INC-002 only;
  - verified link DEP-102; 0 corroborating logs; MEDIUM strength;
  - the summary's "following the deployment" sentence was moved to hypotheses, and the answer gives the recorded cause (JWT signing key mismatch).
- **Multi-incident**, "differences in root causes … gateway high API error rate and slow report loading" (trace `53ae90d0…`):
  - retrieval: INC-012, INC-007, INC-005, INC-014; match: INC-012 + INC-007 (both needed);
  - both deployments verified; MEDIUM strength.

**Status classes:** ✅ implemented and verified · 🟡 implemented, needs improvement · ⛔ not implemented · ❔ not verified against real services.

## 1. Data ingestion and integrity

| Capability | Implementation | Evidence it works | Known failure / limitation | Change made this round | Validation | Status |
|---|---|---|---|---|---|---|
| Required fields, ID uniqueness | `utils/data_integrity.py` | tests; real seed (0 errors) | — | — | `test_data_integrity.py` | ✅ |
| Type validation | same | new tests | non-string fields were accepted | added `incident_bad_type` (error) and `unknown_severity` (warning) | `test_wrong_types_are_errors`, `test_unknown_severity…` | ✅ |
| Incident → deployment FK and service consistency | `check_integrity`, `deployment_link_status` | 12 verified, 8 quarantined on real data | 8 links point at other services | second review (§7); none corrected | `TestRealDataset`, `TestJoins` | ✅ (data needs a human) |
| Documented cross-service dependencies | `service_dependencies.json`, which requires a `source` | fixture tests | none documented in the README or the technical report | — | `test_documented_dependency_*` | ✅ |
| Log provenance and service identity | `corroborating_logs`, non-specific-message check | 4/4 messages flagged on real data | **logs carry no service-specific signal** | — | `TestLogCorroboration` | 🟡 (the data is insufficient) |
| Invalid / unparseable logs | log parser | new test | malformed lines and impossible timestamps were dropped silently | `unparseable_log_lines` warning; timestamp validation | `test_invalid_log_timestamp_is_flagged` | ✅ |
| Duplicate detection | ID uniqueness | tests | identical content under different IDs was not detected | `possible_duplicate_incident` warning | `test_unknown_severity_and_duplicate_content_warn` | ✅ |
| **Idempotent ingestion** | `seed.py` upsert with uuid5 IDs | real seed run twice: 20 points, 0 stale | **defect:** a record removed from the source stayed in Qdrant, because the check was `>=` | `qdrant_setup.sync_points`: upsert, delete stale points, verify the exact ID set | `test_repeated_ingestion_is_idempotent`, `test_removed_source_record_is_deleted_not_left_stale` | ✅ |
| Review workflow | `data_quality_review.json`; seeding fails if a quarantine is not in the review queue | tests | — | review history plus dataset assessment added | `test_unreviewed_quarantine_fails_ingestion` | ✅ |
| Observable validation | log lines only | — | results were not persisted anywhere | `backend/storage/integrity_report.json`; `/health.data_integrity` | `test_report_is_written`, `test_health_exposes_integrity_status` | ✅ |
| Lineage / source timestamps | none | — | **incidents have no timestamps**; no lineage fields | — | — | ⛔ (needs source data) |

## 2. Retrieval

| Capability | Evidence | Limitation | Decision | Status |
|---|---|---|---|---|
| Chunk metadata (incident ID, service, severity, status, deployment ID) | Qdrant payload | the source has no timestamps | — | ✅ |
| Chunking | one point per incident record, about 15 words | — | no boundary problem possible; left unchanged | ✅ |
| Ranking quality (75 labelled questions) | hit@1 0.907; hit@3/5/10 1.00; recall@5 1.00; MRR 0.953; nDCG@5 0.966 | — | **no hybrid search or reranker:** no retrieval miss exists to fix | ✅ |
| Relevance filter, shared by production and eval | `incident_agent.select_relevant` (floor 0.60, margin 0.10), calibrated on a dev/held-out split | scores cannot separate near-miss from in-scope questions | unchanged | ✅ |
| Service-based filtering | **new** deterministic service gate on match verdicts (see §3) | — | applied after retrieval, not as a vector filter, so named cross-service incidents survive | ✅ |

## 3. Evidence matching

| Capability | Evidence | Limitation | Status |
|---|---|---|---|
| LLM per-incident match (`incident_matcher.py`, gpt-4.1-mini, temperature 0) | unseen set (36): in-scope 20/20, out-of-scope 15/16 declined | 2 arguable false accepts on the test set | 🟡 |
| **New:** named incident IDs are always evidence, and are added if retrieval missed them | test `test_workflow_adds_named_incident_missing_from_retrieval` | — | ✅ |
| **New:** service gate (a question naming services rejects matches on unnamed services, unless a documented dependency exists) | production node: out-of-scope declined 0.85 → **0.90** on the test set. **The +1 is the inspected "leave reports" question the gate was designed from.** Uninspected questions stay at 11/13 and the unseen set at 15/16; no in-scope loss. | covers only questions that name a service | ✅ |
| Root-cause term-overlap rescue | simulated | rescued 0 expected incidents and accepted 1 wrong one on unseen data | **rejected, not implemented** | — |
| Multi-incident recall | full matched recall 0.867 (13/15) | INC-009 described by its root cause; the vague auth + leave question | 🟡 |
| Evaluator uses the production node | `evaluate_matcher` now calls `incident_matching_node` | — | ✅ |

## 4. Relationships and multi-incident investigation

| Capability | Evidence | Status |
|---|---|---|
| Joins only on verified links (same service or a documented dependency); no service-name fallback | `TestJoins`, `TestLogCorroboration` | ✅ |
| Verified relationship vs possible correlation | deployments are carried with `link_status`; correlations become hypotheses only | ✅ |
| **New:** conflict reporting (matched incidents with different recorded causes are reported, not merged) | `test_different_recorded_causes_are_reported` | ✅ |
| Contradiction reporting (quarantined link → LOW confidence plus an explicit note) | tests and real answers (e.g. INC-017) | ✅ |
| Graph database | not needed: 20 incidents, no documented dependencies, no traversal requirement. Recommend only if many-hop dependency analysis on documented service graphs becomes a requirement. | — |

## 5. Grounding and refusal

| Step | Implementation | Evidence | Status |
|---|---|---|---|
| Records validated before use | integrity + verified joins | tests | ✅ |
| Which records address the question | LLM match + deterministic rules | §3 | 🟡 |
| Structured findings (facts / conclusions / hypotheses / unknowns) | `rca_structured.py` JSON | runs | ✅ |
| Citation and ID/date validation | `validate()`; fabricated IDs and dates removed | tests plus prompt-injection test | ✅ |
| **New:** deployment causation/timing guard | `asserts_deployment_causation` (proximity-based, negation-aware, 15 regression cases from real outputs) applies to claims, root cause **and summary**; such claims become hypotheses, and the root cause falls back to the recorded cause | tests; 0.64 interventions per answer on the final run; raw-claim faithfulness 0.889 vs validated 0.881 (the guard does not inflate the score) | ✅ |
| Semantic support of each claim at runtime | **not implemented.** A valid citation proves provenance, not support; semantic support is only measured offline by the judge. | — | ⛔ |
| Confidence capped by evidence | `validate()` | tests | ✅ |
| Uncertainty report when no record matches | policy answer, no LLM call | tests and runs | ✅ |

## 6. Evaluation

| Capability | Evidence | Status |
|---|---|---|
| Gates, full run, Langfuse experiment | final run `69347d73…`: gate exits 0, but refusal is at threshold and relevancy passes by 0.008 (see REPORT §1) | 🟡 |
| **New:** raw vs rendered answers scored separately | relevancy raw 0.643 vs rendered 0.808; faithfulness raw 0.889 vs validated 0.881 (`evals/faithfulness_raw.py`) | ✅ (it exposes relevancy's dependency on presentation) |
| Per-type results; **new** refusal precision/recall | REPORT | ✅ |
| Reference defects | 17 items; **proposed** v1.1 (`testset_v1.1-proposed.jsonl`, `reference_corrections_v1.1.json`) pending human review; v1 unchanged | 🟡 (needs a human) |
| Judge calibration against **human** labels | `claim_labels.csv` and `calibration_samples.csv` exported, human columns empty. The 60 earlier AI labels are kept separately and are not ground truth. | ⛔ (needs a human) |
| Judge batch-size sensitivity | measured last round: batch 1/4/8 → accuracy 0.76/0.71/0.69 against AI labels | 🟡 |

## 7. Production operations and security

| Area | Finding | Change | Status |
|---|---|---|---|
| Structured logging | plain-text `logging` format, not JSON; the production trace ID is not written to the app logs | — | 🟡 |
| Langfuse traces and scores | verified through the API (v5 experiments, observations, scores) | — | ✅ |
| Trace privacy | production traces store question length, counts, model and usage only | — | ✅ |
| Label cardinality | trace names fixed; tags = question type; metadata bounded | — | ✅ |
| **Observability failure never alters results** | was untested | new test: every Langfuse call raises → identical result | ✅ |
| Backoff with jitter; quota handling | unit tests; **real** Gemini 503 → `transient`; **real** Gemini 429 → `quota_exhausted`, 1 attempt, 0.9 s | — | ✅ (a real backoff-then-success was not observed) |
| **Timeouts** | **defect:** the Gemini timeout was passed in ms where google-genai 0.6 expects seconds, making it 60,000 s. This explains the 191–214 s calls. | fixed to `GEMINI_TIMEOUT_MS/1000`; tests for both providers | ✅ unit · ❔ not checked against a real slow call |
| Cancellation | an SSE client disconnect does not cancel the running LLM call | — | ⛔ |
| Cache identity | provider, model, options and exact prompt; prompt or evidence changes regenerate | verified earlier | ✅ |
| Concurrency | 64 concurrent unlocked production searches = serial results | — | ✅ (single process) |
| Deployment mode | embedded Qdrant locks its folder: **one process only** (multi-worker uvicorn, or tests alongside a server, fail with a lock error, observed this round) | documented | 🟡 |
| **Authentication / authorization / tenant isolation** | **none in the API or frontend** | — | ⛔ |
| `permission_leaks == 0` | meaningless: there is no permission metadata and 0 tests | — | ⛔ |
| Input validation | pydantic, 8–500 characters, blank rejected | existing tests | ✅ |
| Prompt injection | no tools or actions; fabricated IDs and dates removed deterministically (new test) | the model can still word misleading text around valid citations | 🟡 |
| Secrets | `.env` git-ignored; no keys in the diff or untracked files (scanned) | — | ✅ |
| Safe errors | generic error envelope | existing tests | ✅ |
| Rate limiting | in-memory, per IP, single process | — | 🟡 |
| CI workflow | **reproduced locally** in a fresh venv: install, pip check, tests (147 at the time; 153 now), seed into a fresh Qdrant path, idempotent upload, eval gate (fails correctly on a noisy 6-question sample), report | **added a unit-test step**; it was missing | ✅ local · ❔ not run on GitHub |
| Lint / type check | none configured for the backend | — | ⛔ |
| OpenAI path | real runs | — | ✅ |
| Gemini path | earlier real plain call OK. **JSON mode: blocked by a real 503, then by the free-tier daily quota.** | — | ❔ |
