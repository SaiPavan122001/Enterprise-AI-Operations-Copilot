# Remaining Defects — register

**Baseline verified on 2026-10-24** against run `…152902Z` (Langfuse experiment `69347d73e79d0162`): 153 tests pass, and every number below was re-read from `evals/runs/<run>/results.jsonl`.

**Status values:** OPEN, FIXED, PARTIAL, BLOCKED-HUMAN. The status column is updated at the end of this round (see the bottom of this file).

| # | Defect | Evidence (trace / file) | Likely root cause | Proposed fix | Validation criteria | Status |
|---|---|---|---|---|---|---|
| D1 | Out-of-scope false accept: "issues with the reporting of analytics data" → INC-014, INC-020 | `7132ec52…`; match verdict `same_problem` for "Dashboard metrics incorrect" and "Scheduled reports not generated" | a single LLM verdict compares one coarse "asked problem" with record titles; no independent second signal | decompose the question into its asked problems; add an independent, non-LLM second signal per (asked problem, record) | held-out out-of-scope rejection improves with no in-scope recall loss || PARTIAL |
| D2 | Out-of-scope false accept: "failure in the payroll reconciliation process" → INC-001, INC-015 | `8fa27859…` | same as D1 (payroll is named, so the service gate cannot help) | same as D1 | same as D1 || PARTIAL |
| D3 | Multi-incident: INC-009 dropped ("database structure **and** batch job execution") | matcher output `matched=[INC-001]` | one asked problem per question; INC-009 is described by its cause, not its symptom | per-requirement decomposition: each requirement is matched separately | held-out multi-incident full recall ≥ the current 0.867 || FIXED |
| D4 | Multi-incident: "root causes of incidents in auth-service and leave-service" → nothing matched | `65398a4c…` | the question asks for incidents by service; the matcher wants one symptom | decomposition handles "incidents on service X" requirements | answered from the auth and leave incidents; not refused || FIXED |
| D5 | Multi-incident relevancy 0.674 (baseline 0.800); 2 "false refusals" on "how did X affect Y" | `62305b4e…`, `ffb4ce64…` | the answer reduces to "no record connects them"; per-incident facts are lost from the summary | a relationship-question contract: per-incident findings + an explicit relationship status | multi-incident relevancy (rendered **and raw**) improves; no invented links || PARTIAL |
| D6 | Raw-summary relevancy 0.643 vs rendered 0.808 | summary.json | the model hedges in the summary; the rendered score depends on caveat relocation | a direct-answer summary contract measured on raw output; presentation unchanged | raw relevancy improves; reported separately || PARTIAL |
| D7 | No runtime claim-support validation (a valid citation proves provenance only) | `rca_structured.validate` | only ID, date and deployment-causation checks exist | deterministic claim checks + a separate local NLI verifier; uncertain claims are downgraded | verifier precision and recall on labelled adversarial examples; adversarial tests || PARTIAL |
| D8 | 8 quarantined incident→deployment links | `backend/data/data_quality_review.json` | the source data references other services' deployments | human decision; review report; strict-mode seeding | no link changed without a reviewer decision || BLOCKED-HUMAN |
| D9 | Logs carry no service-specific signal; incidents have no timestamps | integrity report | synthetic placeholder data (to be confirmed by the owner) | versioned regeneration *plan* (not applied); strict validation | plan reviewed by the owner || BLOCKED-HUMAN |
| D10 | Judge not human-calibrated | `claim_labels.csv`: human column empty | needs a human | review export + label validator; agreement only on human labels | human labels supplied || BLOCKED-HUMAN |
| D11 | 17 proposed reference corrections unreviewed | `reference_corrections_v1.1.json` | needs a human | review report + approval CSV + apply script (approved rows only) | v1 untouched; v1.1 built only from approved rows || BLOCKED-HUMAN |
| D12 | No authentication or authorization | `api/routes.py`; the frontend sends no credentials | not built | single-tenant API-key authentication (FastAPI security, hashed keys, roles), fail-closed | negative tests: missing, invalid or forged credentials; wrong role || FIXED |
| D13 | No request cancellation | the workflow runs to completion after a client disconnect | no cancellation propagation | cooperative cancellation token checked between stages, before LLM calls and during backoff; disconnect detection | cancellation tests at each stage || FIXED |
| D14 | No lint or type check | no tooling | — | ruff + mypy configs, dev requirements, CI step; fix the errors found | clean lint and type check; CI step || FIXED |
| D15 | Unstructured logs; no request or investigation IDs | `config.configure_logging` | — | JSON formatter (opt-in), request-ID middleware, context fields; no question text | log-field tests || FIXED |
| D16 | In-process rate limiter assumes a single process; embedded Qdrant is single-process | `utils/rate_limit.py`, Qdrant lock | — | document; key the limiter by authenticated identity; startup guard against multi-worker | documented + tests || PARTIAL |
| D17 | Gemini JSON mode unverified | real API: 503, then quota | free-tier quota | retry when quota allows; otherwise keep marked unverified | one real JSON call || OPEN |
| D18 | GitHub Actions never run on GitHub | — | not pushed (no permission to push) | local reproduction only | — | BLOCKED-HUMAN (push permission) |

## Outcome of this round (final run `…083052Z_r5-final2`, Langfuse `ba863202bc2f3e33`)

| # | Status | What was done / why not closed |
|---|---|---|
| D1, D2 | PARTIAL | Stage A unchanged (still accepts both). A non-LLM similarity gate was measured and rejected: it cannot separate these from true matches without tuning to the two inspected questions. New deterministic constraints (service, severity, generic requirements) do not apply to these questions. Held-out out-of-scope rejection stays 15/15. |
| D3, D4 | FIXED | Requirement decomposition (Stage B, gap-filling only). Held-out multi-incident full recall 0.737 → 0.895; dev: only D3/D4 changed. D4 now matches all 5 auth/leave incidents (the question does not say which). |
| D5 | PARTIAL | Multi-incident contract + relationship status enforced in code: false refusals 3 → 0, raw relevancy 0.585 → 0.604, context recall 0.606 → 0.672; rendered relevancy 0.674 → 0.666 (not improved). A padded intermediate result (0.712) was discarded. |
| D6 | PARTIAL | Raw relevancy 0.643 → 0.646; still depends on caveat relocation for the 0.80 gate. |
| D7 | PARTIAL | Deterministic + NLI claim-support checks at runtime. Labelled-by-construction set: precision 1.00, recall 0.553, FPR 0.00 (stated claims). Version 1 rejected after real-answer false positives. Also fixed: ISO deployment dates were not recognised as evidence. |
| D8, D9 | BLOCKED-HUMAN | Review report + decision CSV + validated apply script; strict seeding; stale-review guard; provenance marked unconfirmed; regeneration plan v2 (not applied). |
| D10, D11 | BLOCKED-HUMAN | Blind review exports from the final run; validator, merge, agreement guard (refuses with 0 labels); v1.1 built only from approved corrections (v1 unchanged). |
| D12 | FIXED | Single-tenant API-key auth with roles, fail-closed, 25 negative tests. Gap: a browser-held key is not secret (needs SSO/BFF). |
| D13 | FIXED | Cooperative cancellation at every stage, before LLM attempts and during backoff; disconnect detection verified with real curl disconnects (a middleware defect that hid disconnects from `/investigate` was found and fixed); not tested from a browser. In-flight HTTP calls are not interrupted. |
| D14 | FIXED | ruff + mypy clean (67 type errors fixed, incl. a latent `log_agent` crash); `lint.yml` CI (not run on GitHub). |
| D15 | FIXED | Context-carrying logs (request/investigation/stage/principal), JSON option, per-stage and per-LLM-call lines, redaction, no question/prompt/answer text. |
| D16 | PARTIAL | Rate limiter keyed by identity, documented single-process limits, startup error for `WEB_CONCURRENCY>1`. Multi-process still needs Qdrant server + shared store. |
| D17 | OPEN | Real Gemini JSON call timed out 3× (60 s each — confirms the timeout fix). JSON mode still unverified. |
| D18 | BLOCKED-HUMAN | CI not run on GitHub. |
