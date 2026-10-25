# Human input needed (round 6)

Checked 2026-10-24. **No human input has been provided yet.** Every human field in the review files below is empty. Nothing was guessed, filled in by an AI, or applied.

| Item | File to fill in | What to enter | Then run | Status |
|---|---|---|---|---|
| 60 claim labels (judge calibration) | `evals/calibration/review/claims_blind.csv` | `human_label` = `supported` \| `unsupported` \| `contradicted` \| `indeterminate`, judged only from the `evidence` column (judge verdicts are hidden) | `python -m evals.human_review validate`, then `merge`, then `python -m evals.claim_calibration agreement --labels human` | 0/60 |
| 100 judge samples | `evals/calibration/review/samples_blind.csv` | `human_label` = `1` (deserves to pass the named metric) or `0` | `validate`, `merge`, then `python -m evals.calibration agreement` | 0/100 |
| 17 reference corrections | `evals/calibration/review/reference_corrections_review.csv` | `decision` = `approve` \| `edit` (text in `edited_reference`) \| `reject`, plus `reviewer` | `python -m evals.human_review build-v1.1` | 0/17 |
| 8 quarantined deployment links | `backend/data/review/link_decisions.csv` (context: `LINK_REVIEW.md`) | `decision` = `replace` (with `new_deployment_id`) \| `none` \| `keep_quarantined`, plus `reviewer` and `source` for `replace`/`none` | `cd backend && python -m scripts.link_review check`, then `apply --apply`, then `python -m scripts.seed` | 0/8 |
| Dataset provenance | `backend/data/data_quality_review.json` → `dataset_assessment.provenance.status` | `synthetic` or `real`, with a source | — | unconfirmed |
| Regeneration plan v2 | `backend/data/REGENERATION_PLAN.md` | approve or reject (only if the data is synthetic) | — | not decided |

## Safeguards already in place

- **Judgements kept separate.** AI and human judgements are separate columns, and the blind files contain no judge or AI labels. `merge` refuses to overwrite a different existing human label.
- **Agreement needs real labels.** Agreement refuses to run with zero human labels, so no calibration number can be produced without them.
- **`testset_v1.jsonl` is never modified** (sha256 `962bf199…`). `testset_v1.1.jsonl` is built once, only from approved or edited rows, and records the reviewer per item.
- **Audit trail:**
  - `merge` copies each calibration CSV to `<name>.pre-merge-<timestamp>.csv` before writing.
  - `merge` and `build-v1.1` append to `evals/calibration/review/AUDIT_LOG.jsonl` (action, time, counts, reviewers).
  - `link_review apply` copies `incidents.json` to `backend/data/versions/`, appends to each link's `review_history`, and writes `backend/data/review/AUDIT_LOG.jsonl`.
- **No guessed links.** A link decision of `none` needs a reviewer and a source, and a `replace` must name a deployment on the incident's own service. An empty decision is never treated as `none`.

## Calibration agreement this round

**Not computable:** 0 human labels. The only labels that exist are AI provisional labels (`claim_labels_run20261023T124048Z_ai_provisional.csv`). They are not ground truth and are not reported as calibration.
