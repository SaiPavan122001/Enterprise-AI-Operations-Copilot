# Synthetic data regeneration plan (v2) — **proposal, not applied**

**Status:** awaiting the data owner's decision. Nothing in `backend/data/` has been regenerated or repaired.
**Applies to:** dataset v1, the current `incidents.json`, `deployments.json` and `logs.txt`. v1 stays frozen.
**Prerequisite:** the owner confirms the dataset is synthetic (`dataset_assessment.provenance.status` in `data_quality_review.json`, currently `unconfirmed`). If the records are real, this plan does not apply: real data must be corrected at its source, using the link review in `review/LINK_REVIEW.md`.

## 1. Why regenerate

| Defect in v1 | Evidence | Effect on the copilot |
|---|---|---|
| 8 incidents reference a deployment on another service | `data_quality_review.json` (INC-008, -009, -010, -011, -017, -018, -019, -020) | those links are quarantined, so 8 of 20 incidents have no deployment evidence |
| Deployment change descriptions don't fit their service (e.g. DEP-116 on auth-service: "Search index refresh"; DEP-115 on payroll-service: "Ingress configuration change") | `deployments.json`; see the deployment tables in `review/LINK_REVIEW.md` | a deployment's description can't support an answer about its service |
| Logs carry no service-specific signal: each of the 4 non-INFO messages appears on all 7 services | integrity report: `log_message_not_service_specific` | logs never corroborate an incident, so evidence strength can never reach HIGH |
| Incidents have no start/end timestamps | `incidents.json` | no temporal relationship to a deployment can be shown; timelines are deployment-only |
| No documented service dependencies | `service_dependencies.json` is empty | cross-service links can never be verified |

## 2. Principles

1. **Versioned, never in place.** v2 goes in `backend/data/v2/` with a `MANIFEST.json`. v1 files stay byte-identical, and existing eval runs and test sets keep pointing at v1.
2. **Labelled synthetic.** `MANIFEST.json` records `provenance: "synthetic"`, the generator script and version, the RNG seed and the source of each field. Answers built from v2 can say their evidence is synthetic.
3. **Consistent by construction, checked by code.** Each incident is generated from one scenario that sets the service, the deployment (same service), the change description, the incident start time (after the deployment), and log lines (same service, matching the symptom, within the window). The generator runs `check_integrity` and `strict_problems`, and refuses to write v2 unless strict ingestion passes, apart from the provenance check, which v2 satisfies by declaring itself synthetic.
4. **Deliberate negatives.** Some incidents have **no** deployment, and some deployments have **no** incident, so the copilot is tested on "no deployment link" answers. Any cross-service dependency is listed in `service_dependencies.json` with a `source`, and only one that is documented may be used.
5. **No reuse of v1 links.** v2 does not "fix" the 8 v1 links by picking a same-service deployment. v1 remains the historical record of what the data said.

## 3. Proposed v2 contents (for review)

| File | Change |
|---|---|
| `incidents.json` | same 20 problems (titles, root causes, services, severities); adds `started_at`/`resolved_at`; `deployment_id` only where the scenario has one |
| `deployments.json` | one change description per service that plausibly relates to that service; times spread realistically (not one per day at 10:03, 10:06, …) |
| `logs.txt` | per-incident ERROR/WARN lines on the incident's service, with the symptom's wording, between deployment and incident end; plus background INFO and unrelated noise on other services |
| `service_dependencies.json` | only dependencies the owner documents (may stay empty) |
| `MANIFEST.json` | version, provenance, generator, seed, checksums, integrity summary |

## 4. Evaluation impact (decide before regenerating)

- `testset_v1.jsonl` references and the 17 proposed corrections (`testset_v1.1-proposed.jsonl`) are tied to v1 data, so v2 needs its own test set (`testset_v2`). Its held-out matcher set must be generated **after** v2 and never inspected during tuning.
- Results on v1 and v2 are not comparable. Reports would show them side by side and must not mix them.
- The deployment-causation guard still applies: v2 records will still not *state* that a deployment caused an incident unless the scenario says so explicitly and the owner accepts that.

## 5. Acceptance checks for v2

- `python -m scripts.seed --strict` passes against v2.
- Integrity report: 0 errors, 0 quarantined links, 0 non-specific non-INFO log messages.
- Every incident with a deployment: the same service (or a documented dependency), and the deployment time is before `started_at`.
- Every incident has at least 1 corroborating log line, except the deliberate negatives listed in the manifest.
- `pytest backend/tests` passes, with v1-specific assertions moved to v1 fixtures.

## 6. Decisions needed from the data owner

1. Is v1 synthetic or real? (sets `provenance.status`)
2. If synthetic: approve regeneration, and say whether the 20 problems should stay the same.
3. Which (if any) cross-service dependencies exist, and their source documents.
4. Whether the evaluation moves to v2 (new test set) or stays on v1 with the link review applied.
