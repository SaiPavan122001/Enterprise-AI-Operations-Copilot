"""Human review workflow for judge calibration and reference corrections.

    python -m evals.human_review export      # blind review files + guide (human fields empty)
    python -m evals.human_review validate    # check what reviewers filled in (no writes)
    python -m evals.human_review merge       # copy validated human labels into the calibration CSVs
    python -m evals.human_review build-v1.1  # testset_v1.1.jsonl from APPROVED corrections only

Blind: the review files contain the question, claim/answer and evidence, but NOT the judge's
verdict or any AI label, so reviewers are not anchored. Labels are joined back by ID.
Nothing here fills in a human field: empty stays empty. Agreement is computed afterwards by
``python -m evals.claim_calibration agreement`` and ``python -m evals.calibration agreement``,
which refuse to run without human labels.
testset_v1.jsonl is never modified; v1.1 is a new file built only from approved rows.
"""

import csv
import json
import shutil
import sys
from datetime import date, datetime, timezone

from evals.settings import repo_path

CLAIMS = "evals/calibration/claim_labels.csv"
SAMPLES = "evals/calibration/calibration_samples.csv"
CORRECTIONS = "evals/testsets/reference_corrections_v1.1.json"
REVIEW_DIR = "evals/calibration/review"
CLAIMS_BLIND = f"{REVIEW_DIR}/claims_blind.csv"
SAMPLES_BLIND = f"{REVIEW_DIR}/samples_blind.csv"
REFS_REVIEW = f"{REVIEW_DIR}/reference_corrections_review.csv"
V1, V11 = "evals/testsets/testset_v1.jsonl", "evals/testsets/testset_v1.1.jsonl"

CLAIM_LABELS = ("supported", "unsupported", "contradicted", "indeterminate")
SAMPLE_LABELS = ("0", "1")
REF_DECISIONS = ("approve", "reject", "edit")
AUDIT_LOG = f"{REVIEW_DIR}/AUDIT_LOG.jsonl"


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _audit(action: str, **details) -> None:
    """Append-only record of every change made from human review input."""
    p = repo_path(AUDIT_LOG)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps({"at": _stamp(), "action": action, **details}, ensure_ascii=False) + "\n")


def _archive(path: str) -> str:
    """Copy a file before it is changed: <name>.pre-<action>-<stamp><ext>."""
    src = repo_path(path)
    dst = src.with_name(f"{src.stem}.pre-merge-{_stamp()}{src.suffix}")
    shutil.copy2(src, dst)
    root = repo_path("x").parent
    return str(dst.relative_to(root)) if dst.is_relative_to(root) else str(dst)


def _read(path):
    with open(repo_path(path), encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _write(path, rows, fields):
    p = repo_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def _has_human_input(path, cols) -> bool:
    p = repo_path(path)
    return p.exists() and any(r.get(c, "").strip() for r in _read(path) for c in cols)


def export() -> int:
    targets = [(CLAIMS_BLIND, ("human_label", "human_note")), (SAMPLES_BLIND, ("human_label", "human_notes")),
               (REFS_REVIEW, ("decision", "edited_reference", "reviewer", "note"))]
    for path, cols in targets:
        if _has_human_input(path, cols):
            raise SystemExit(f"{path} already contains reviewer input - not overwritten")
    claims = _read(CLAIMS)
    _write(CLAIMS_BLIND, [{"claim_id": r["claim_id"], "question": r["question"], "claim": r["claim"],
                           "evidence": r["evidence"], "human_label": "", "human_note": ""} for r in claims],
           ["claim_id", "question", "claim", "evidence", "human_label", "human_note"])
    samples = _read(SAMPLES)
    _write(SAMPLES_BLIND, [{"sample_id": r["sample_id"], "metric": r["metric"], "question": r["question"],
                            "reference_answer": r["reference_answer"], "retrieved_contexts": r["retrieved_contexts"],
                            "answer_evaluated": r["answer_evaluated"], "human_label": "", "human_notes": ""}
                           for r in samples],
           ["sample_id", "metric", "question", "reference_answer", "retrieved_contexts", "answer_evaluated",
            "human_label", "human_notes"])
    corr = json.loads(repo_path(CORRECTIONS).read_text(encoding="utf-8"))["corrections"]
    _write(REFS_REVIEW, [{"id": c["id"], "question": c["question"], "old_reference": c["old_reference"],
                          "proposed_reference": c["proposed_reference"], "evidence": " | ".join(c["evidence"]),
                          "decision": "", "edited_reference": "", "reviewer": "", "note": ""} for c in corr],
           ["id", "question", "old_reference", "proposed_reference", "evidence", "decision", "edited_reference",
            "reviewer", "note"])
    metrics = sorted({r["metric"] for r in samples})
    items = "\n".join(f"""### {n}. `{c['id']}` ({c['question_type']})
**Question:** {c['question']}

| | Reference |
|---|---|
| v1 (current) | {c['old_reference']} |
| proposed v1.1 | {c['proposed_reference']} |

Evidence: {'; '.join(c['evidence'])}
""" for n, c in enumerate(corr, start=1))
    repo_path(f"{REVIEW_DIR}/REVIEW_GUIDE.md").write_text(f"""# Human review guide

Generated {date.today().isoformat()} by `python -m evals.human_review export`. All human fields are empty.
The files are **blind**: they omit the judge's verdict and every AI label, so record your own judgement.

## 1. Claim labels: `claims_blind.csv` ({len(claims)} claims from the final run)
For each claim, read only the `evidence` column (the records the answer had) and set `human_label`:
- `supported`: the evidence states it, or it follows directly
- `unsupported`: the evidence does not establish it (it may be plausible, but it is not in the records)
- `contradicted`: the evidence says otherwise
- `indeterminate`: you cannot tell from the evidence shown (excluded from agreement)

## 2. Judge samples: `samples_blind.csv` ({len(samples)} rows; metrics: {', '.join(metrics)})
Set `human_label` to `1` if the answer deserves to PASS the named metric, otherwise `0`.

## 3. Reference corrections: `reference_corrections_review.csv` ({len(corr)} items)
v1 references for these questions assert deployment links the data does not support (quarantined links).
Set `decision` = `approve` (use the proposed text) | `edit` (put your text in `edited_reference`) |
`reject` (keep v1), and fill in `reviewer`. Questions are never changed.

## After review
```
python -m evals.human_review validate
python -m evals.human_review merge
python -m evals.claim_calibration agreement --labels human
python -m evals.calibration agreement
python -m evals.human_review build-v1.1
```
`testset_v1.jsonl` stays unchanged. `testset_v1.1.jsonl` contains v1 with only the approved or edited
references replaced.

## Reference corrections for review

{items}""", encoding="utf-8")
    print(f"Wrote {CLAIMS_BLIND} ({len(claims)}), {SAMPLES_BLIND} ({len(samples)}), {REFS_REVIEW} ({len(corr)}) "
          f"and {REVIEW_DIR}/REVIEW_GUIDE.md - all human fields empty")
    return 0


def validate(quiet: bool = False) -> dict:
    problems, counts = [], {}
    for path, key, allowed in ((CLAIMS_BLIND, "claim_id", CLAIM_LABELS), (SAMPLES_BLIND, "sample_id", SAMPLE_LABELS)):
        rows = _read(path)
        filled = [r for r in rows if r["human_label"].strip()]
        problems += [f"{path}: {r[key]} has invalid label {r['human_label']!r} (use {', '.join(allowed)})"
                     for r in filled if r["human_label"].strip() not in allowed]
        counts[path] = f"{len(filled)}/{len(rows)} labelled"
    refs = _read(REFS_REVIEW)
    for r in refs:
        d = r["decision"].strip().lower()
        if not d:
            continue
        if d not in REF_DECISIONS:
            problems.append(f"{REFS_REVIEW}: {r['id']} has invalid decision {d!r}")
        elif not r["reviewer"].strip():
            problems.append(f"{REFS_REVIEW}: {r['id']} decision without a reviewer")
        elif d == "edit" and not r["edited_reference"].strip():
            problems.append(f"{REFS_REVIEW}: {r['id']} 'edit' without edited_reference")
    counts[REFS_REVIEW] = f"{sum(1 for r in refs if r['decision'].strip())}/{len(refs)} decided"
    if not quiet:
        for k, v in counts.items():
            print(f"{k}: {v}")
        for p in problems:
            print("INVALID", p)
    return {"counts": counts, "problems": problems}


def merge() -> int:
    v = validate()
    if v["problems"]:
        raise SystemExit("Fix the invalid entries first - nothing merged")
    merged = 0
    for blind, target, key, note_in, note_out in (
            (CLAIMS_BLIND, CLAIMS, "claim_id", "human_note", "human_note"),
            (SAMPLES_BLIND, SAMPLES, "sample_id", "human_notes", "human_notes")):
        labels = {r[key]: r for r in _read(blind) if r["human_label"].strip()}
        if not labels:
            continue
        archived = _archive(target)
        rows = _read(target)
        for r in rows:
            b = labels.get(r[key])
            if b is None:
                continue
            if r["human_label"].strip() and r["human_label"].strip() != b["human_label"].strip():
                raise SystemExit(f"{target}: {r[key]} already has a different human label - not overwritten")
            r["human_label"], r[note_out] = b["human_label"].strip(), b[note_in].strip()
            merged += 1
        _write(target, rows, list(rows[0].keys()))
        _audit("merge_human_labels", target=target, source=blind, labels=len(labels), original_saved_as=archived)
    print(f"Merged {merged} human label(s). Next: python -m evals.claim_calibration agreement --labels human")
    return 0


def build_v11() -> int:
    v = validate(quiet=True)
    if [p for p in v["problems"] if p.startswith(REFS_REVIEW)]:
        raise SystemExit("Invalid reference decisions - run validate")
    out = repo_path(V11)
    if out.exists():
        raise SystemExit(f"{V11} exists - v1.1 is built once; delete it deliberately to rebuild")
    decided = {r["id"]: r for r in _read(REFS_REVIEW) if r["decision"].strip().lower() in ("approve", "edit")}
    if not decided:
        raise SystemExit("No approved corrections - v1.1 not built (v1 remains the test set)")
    corr = {c["id"]: c for c in json.loads(repo_path(CORRECTIONS).read_text(encoding="utf-8"))["corrections"]}
    items = [json.loads(line) for line in open(repo_path(V1), encoding="utf-8") if line.strip()]
    changed = []
    for it in items:
        r = decided.get(it["id"])
        if r:
            new = r["edited_reference"].strip() if r["decision"].strip().lower() == "edit" \
                else corr[it["id"]]["proposed_reference"]
            it.update(reference_answer=new, testset_version="v1.1",
                      reference_review={"reviewer": r["reviewer"].strip(), "decision": r["decision"].strip().lower(),
                                        "note": r["note"].strip(), "date": date.today().isoformat()})
            changed.append(it["id"])
        else:
            it["testset_version"] = "v1.1"
    with open(out, "w", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    _audit("build_testset_v1.1", output=V11, base=V1, approved=[
        {"id": i, "decision": decided[i]["decision"].strip().lower(), "reviewer": decided[i]["reviewer"].strip()}
        for i in changed])
    print(f"Wrote {V11}: {len(items)} items, {len(changed)} reviewer-approved reference(s) replaced; "
          f"{len(corr) - len(changed)} proposed correction(s) not approved (v1 reference kept). v1 unchanged.")
    return 0


def main(argv=None) -> int:
    cmd = (argv or sys.argv[1:] or [""])[0]
    actions = {"export": export, "validate": lambda: 1 if validate()["problems"] else 0, "merge": merge,
               "build-v1.1": build_v11}
    if cmd not in actions:
        raise SystemExit(__doc__)
    return actions[cmd]()


if __name__ == "__main__":
    sys.exit(main())
