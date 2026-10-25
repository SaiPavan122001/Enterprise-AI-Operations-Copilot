# Reliability Audit — Enterprise AI Operations Copilot

**Updated:** 2026-10-24 (round 5: "close remaining reliability defects"). **Branch:** `main`. All work is uncommitted; nothing was committed, pushed or deployed. The round-4 version is kept as `RELIABILITY_AUDIT_round4.md`.

**Source of truth:** code, tests and run artifacts. The defect-by-defect status is in `REMAINING_DEFECTS.md`, and the numbers are in `REPORT.md`.

**Architecture:**
- FastAPI, LangGraph and React.
- Data: JSON files plus **embedded Qdrant** (20 points). There is no relational database.

**Status classes:** ✅ implemented and verified · 🟡 implemented, needs improvement · ⛔ not implemented · ❔ not verified against real services · 👤 blocked on a human decision.

## 1. Data ingestion and integrity

| Capability | State this round | Validation | Status |
|---|---|---|---|
| Required fields, types, uniqueness, duplicates, unparseable logs | unchanged from round 4 | `test_data_integrity.py` | ✅ |
| Incident → deployment service consistency | 12 verified, 8 quarantined. **New:** a review covers one exact (incident, deployment) pair. Pointing a quarantined incident at *another* unverified deployment is now an error (`stale_quarantine_review`) and does not inherit the old review. | `test_data_review.py::TestQuarantineReviewBinding` | ✅ |
| **New:** strict ingestion (`python -m scripts.seed --strict`, or `SEED_STRICT=1`) | refuses unless every link verifies, logs are service-specific and provenance is confirmed real. The repository data is refused, correctly: 8 links + logs + provenance. | `TestStrictIngestion` | ✅ (default seeding unchanged) |
| **New:** dataset provenance | `dataset_assessment.provenance.status = "unconfirmed"`, with observations (sequential IDs; one deployment per day, each 3 minutes later; identical log messages on all services). Shown in `/health` and the integrity report. | `test_provenance_defaults_to_unconfirmed` | 👤 owner must confirm synthetic or real |
| **New:** human link review | `python -m scripts.link_review export \| check \| apply --apply` writes `backend/data/review/LINK_REVIEW.md` and `link_decisions.csv` (decisions empty; no replacement suggested). `none` is applied only with a reviewer and a source. A replacement must verify. The original file is versioned before any write. | `TestReviewerDecisions` | ✅ tooling · 👤 decisions |
| **New:** regeneration plan v2 | `backend/data/REGENERATION_PLAN.md`: versioned, labelled synthetic, consistent by construction, strict seeding as the acceptance gate. **Not applied.** | review | 👤 |
| Log service signal; incident timestamps | unchanged: insufficient in the source data | — | ⛔ (needs data) |

## 2. Retrieval
Unchanged: hit@5 1.00, MRR 0.953, no retrieval misses on the dev sets. In-scope questions never lose their expected incident at retrieval (0/75 on testset_v1).

## 3. Evidence matching (Phase 2)

| Capability | Evidence | Status |
|---|---|---|
| **Stage A**: the per-record verdict from round 4, prompt **byte-identical** | dev re-runs against the round-4 matcher outputs: every question Stage B did not change kept exactly the same verdicts (Stage A calls served from cache); no out-of-scope verdict changed (final dev comparison: 93/95 and 36/36 identical; the 2 changes are D3 and D4) | ✅ |
| **Stage B (new)**: requirement decomposition. A separate call (no records shown) splits the question into requirements (symptom, cause, service, id). Each requirement is judged **independently**. Stage B only **fills gaps**: a requirement Stage A already covers adds nothing. | D3 (INC-009 described by its cause) and D4 (incidents requested by service) recovered on dev. **Held-out (46 questions, never inspected, run once after freezing): multi-incident full recall 0.737 → 0.895; in-scope full recall 0.839 → 0.935; out-of-scope rejection 1.0 → 1.0; matched precision 1.0 → 0.981.** | ✅ |
| **New hard constraints in code** | per-requirement service (only services the question names; documented dependencies allowed); **severity** named in the question ("critical", "high-severity") is a hard filter; **generic requirements** ("root causes of the incidents") become "incidents on <service>" or are dropped; a "service" requirement needs a service the question names | `test_matcher_requirements.py` (24 tests) | ✅ |
| Non-LLM second safeguard for false accepts (D1/D2) | **Measured, not shipped.** bge similarity (question vs title, title+cause) cannot separate the D1/D2 false accepts (0.68–0.79) from true matches (14–43 of 110 true matches score lower). A threshold would drop true matches or be tuned to the two inspected questions. The deterministic safeguards above are the second layer instead. | 🟡 D1/D2 remain |
| Fail-soft | decomposition failure → Stage A verdicts; a requirement failure never adds evidence | `TestFailSoft` | ✅ |
| Cost | +1 LLM call per question (decomposition); +1 per requirement on multi-requirement questions | — | 🟡 latency |

## 4. Multi-incident answers (Phase 3)

| Capability | Evidence | Status |
|---|---|---|
| Multi-incident prompt contract: `question_focus` (relationship / individual), `per_incident` findings, `relationship` status. Added **only** when ≥2 incidents matched, so single-incident prompts are byte-identical. | single-incident metrics unchanged in the final run (REPORT §1) | ✅ |
| Relationship status enforced in code: "documented" only when a record links the incidents (same verified deployment, or a documented service dependency). The statement is then generated from that record and says no record states causation. Otherwise "not_established". | `TestDirectCausation`, `TestTemporalCorrelation`, `TestDocumentedDependency` | ✅ |
| Inter-incident causal claims ("INC-014 affected INC-013") as facts or conclusions → hypotheses (clause-level, negation-aware, passive "caused by" excluded) | 9-case detector test + contract tests | ✅ |
| Per-incident findings never dropped: if the summary does not state an incident's recorded findings (e.g. it only says no link is established), the recorded title and root cause are added and this is logged. **Corrected during the round:** the first trigger fired on all 15 multi-incident answers, padding summaries that already answered each incident. The trigger now checks the substance of the findings. | `test_one_sentence_stating_both_causes_is_not_padded`; replay of stored outputs: fires on 0 of 19 | ✅ |
| Raw vs rendered | reported separately (REPORT §1). The rendered score is not used to claim the raw improvement. | ✅ |

## 5. Grounding and claim support (Phase 4)

| Step | Implementation | Evidence | Status |
|---|---|---|---|
| Citation / ID / date validation | unchanged. **Defect fixed:** `evidence_dates` used a trailing word boundary, so ISO timestamps (`2026-05-14T10:00:00`) never yielded their date, and true claims stating a deployment's date were removed (2 in the previous final run) | `test_deployment_date_from_iso_timestamp_is_evidence` | ✅ |
| **New:** deterministic claim checks | named service must belong to a cited record or the application's evidence notes; named severity must match the cited incidents; figures in stated claims must appear in the evidence → otherwise hypothesis | `test_claim_support.py` | ✅ |
| **New:** semantic verifier (local NLI cross-encoder `nli-deberta-v3-xsmall`, revision pinned) | premise = cited records + evidence notes + absence facts. Only p(contradiction) ≥ 0.9 removes a claim. Negation/absence statements are not sent to it, and "not entailed" alone changes nothing. | labelled set by construction (376 claims, through the production validator): **precision 1.0, recall 0.553, FPR 0.0** for stated claims; deterministic-only recall 0.42. Known misses: negated causes 0/20, false absence 0/20, wrong status 1/20, swapped titles 5/20. | 🟡 (high precision, partial recall) |
| **Verifier v1 rejected after measurement** | the first version also demoted "not entailed" claims and judged absence statements | on real answers it made **2.7 interventions per answer**, mostly false positives (true "no log lines corroborate…" statements removed as contradicted), and caused a false refusal | — |
| Unavailable model | deterministic checks still run; the answer records "semantic verifier unavailable" | `test_model_unavailable_is_reported_not_silent` | ✅ |
| Latency | ~0.8 s per answer (12 claims, CPU) + 11 s cold model load; contention under concurrent load (eval median 3.5 s/question vs 0.4 s) | — | 🟡 |

## 6. Evaluation (Phase 6)

| Capability | Evidence | Status |
|---|---|---|
| Gates, full run, Langfuse experiment | REPORT §1 | see REPORT |
| **New:** blind review exports | `evals/calibration/review/`: claims (60) and judge samples (100) **without** judge or AI labels; reference corrections (17) with an approve/edit/reject column; `REVIEW_GUIDE.md` | 👤 |
| **New:** label validation + merge + agreement guard | `python -m evals.human_review validate \| merge`. Agreement now **refuses** to run without human labels; the earlier zero-label `claim_agreement_human.json` was deleted. | ✅ tooling · 👤 labels |
| **New:** v1.1 build from approved corrections only | `python -m evals.human_review build-v1.1`: v1 hash unchanged (`962bf199…`); refuses without approvals; built once | ✅ |
| Held-out matcher set | `testsets/matcher_heldout_v2.jsonl` (46), generated before the redesign, aggregates only | ✅ |

## 7. Production operations and security (Phase 7)

| Area | Change this round | Validation | Status |
|---|---|---|---|
| **Authentication / authorization** | single-tenant API keys (`utils/auth.py`): SHA-256-hashed keys in `API_KEYS`, constant-time compare, roles viewer < investigator < admin; `/search` needs viewer, `/investigate*` needs investigator; `/health` public. **Fail-closed:** no keys → 503; `AUTH_MODE=disabled` only when set explicitly (warned at startup). Frontend sends `VITE_API_KEY` if set. | `test_auth.py` (25): missing, invalid, forged (stored hash sent as key), wrong scheme, wrong role, not configured, unknown mode, per-endpoint | ✅ · see security gaps |
| Tenant isolation | not applicable: single tenant by design; the server stores no per-user data (history and feedback are in browser localStorage) | — | documented |
| **Request cancellation** | cooperative `CancellationToken` checked before every stage, before every LLM attempt and during backoff (the sleep wakes up). `InvestigationCancelled` is a BaseException, so fail-soft handlers cannot swallow it. `/investigate` watches for disconnect; SSE cancels when the stream closes. | `test_cancellation.py`: each of the 9 stages; backoff wake-up < 2 s against a 5 s delay; no call after cancel; matcher does not swallow; disconnect → token; closing the stream stops the workflow; 499; real graph through the full middleware stack. **Real curl disconnects:** the stream cancelled. `/investigate` did not until `BaseHTTPMiddleware` was replaced with a pure ASGI middleware; after that, the LLM attempt was skipped and the response was 499. | ✅ (curl) · ❔ browser |
| In-flight LLM HTTP call | not interruptible; its result is discarded at the next check | — | 🟡 |
| **Structured logging** | `utils/log_context.py`: request, investigation and stage IDs plus principal on every record (also in worker threads); `LOG_FORMAT=json`; one line per stage and per LLM call (provider, model, purpose, duration, outcome, attempts); access log (method, path, status, duration); `X-Request-ID`; credential redaction. **No question, prompt or answer text** (grounding-issue logs now omit claim text). | `test_structured_logging.py` | ✅ |
| **Lint / type check** | `ruff.toml` (E, F, W, B) and `mypy.ini` (check_untyped_defs). 67 type errors fixed, including **one latent bug** (`log_agent`: a log entry without a timestamp would raise `TypeError` in the deployment-window check). CI: `.github/workflows/lint.yml`. | ruff: clean · mypy: 0 errors in 36 files | ✅ local · ❔ not run on GitHub |
| Rate limiting (D16) | keyed by authenticated identity (else IP). Single-process memory is documented in code; startup logs an error if `WEB_CONCURRENCY > 1`. | `TestRateLimitPerIdentity` | 🟡 needs a shared store for multi-process |
| Embedded Qdrant (D16) | one process only (folder lock), documented; observed again this round (tests blocked while the eval ran) | — | 🟡 |
| Timeouts | **verified against a real slow call this round:** the Gemini read timeout fired at 60 s (`read timeout=60.0`) on each of 3 attempts with backoff | real call 2026-10-24 | ✅ |
| Gemini JSON mode (D17) | real call timed out 3 times (60 s each); no JSON response obtained | — | ❔ |
| Supply chain | NLI model revision pinned (`CLAIM_VERIFIER_MODEL_REVISION`); the bge embedding model is still unpinned (pre-existing) | — | 🟡 |
| CI | `rag-eval.yml` (eval gate, HF cache key updated for the NLI model) and new `lint.yml` (ruff, mypy, tests) | reproduced locally | ❔ not run on GitHub (no push permission) |

### Security review (this round's changes)

| Finding | Severity | State |
|---|---|---|
| A browser frontend cannot keep an API key secret: `VITE_API_KEY` is visible to anyone who loads the bundle | High for any non-internal deployment | **open**: put the UI behind SSO or a backend-for-frontend that adds the key server-side (documented in `api.js` and `.env.example`) |
| One key shared by all frontend users means one rate-limit budget and no per-user audit | Medium | open: per-user identity needs SSO |
| `/health` is public and reveals LLM provider/model and data-integrity counts (no record data) | Low | accepted; restrict at the proxy if needed |
| Questions are sent to Langfuse Cloud (JP region) by the existing tracing | Data handling | unchanged; owner decision |
| MCP server (`mcp_server/server.py`) has no auth; safe only on its default stdio transport | Low | documented; do not expose over HTTP |
| Keys: none in tracked or untracked files (scanned); test credentials are assembled at runtime; logs redact key patterns | — | ✅ |
| Prompt injection: no tools or actions; fabricated IDs/dates removed; claim checks added | — | 🟡 (misleading wording around valid citations is still possible) |
| Auth bypass: all protected routes use one `Depends(require_role(...))`; unknown `AUTH_MODE` fails closed | — | ✅ tested |

**Not production-ready.** See REPORT §7 for the full list.
