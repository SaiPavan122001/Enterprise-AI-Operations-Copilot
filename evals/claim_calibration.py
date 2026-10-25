"""Claim-level calibration of the faithfulness judge.

    python -m evals.claim_calibration export [--run RUN] [--n 60]
    python -m evals.claim_calibration agreement [--file CSV] [--labels human|assistant]

``export`` samples individual faithfulness claims (statement + the judge's
supported/unsupported verdict) from a run, balanced between judge verdicts,
with the exact evidence the judge saw inline. Columns:

  judge_verdict     the LLM judge's verdict (supported / unsupported)
  assistant_label   PROVISIONAL label produced by an AI assistant (Claude Code)
                    from the same evidence - NOT a human label
  human_label       for a person: supported | unsupported | contradicted | indeterminate

``agreement`` compares the judge with one label column. The judge must only be
called calibrated on HUMAN labels; assistant labels are evidence for/against a
judge problem, not a calibration.
"""

import argparse
import csv
import json
import math
import random
import sys

from evals.calibration import _latest_run, _load_rows
from evals.settings import repo_path

LABELS = ("supported", "unsupported", "contradicted", "indeterminate")
FIELDS = ["claim_id", "run_name", "item_id", "question_type", "question", "claim", "judge_verdict",
          "judge_reason", "evidence", "assistant_label", "assistant_note", "human_label", "human_note"]
DEFAULT_FILE = "evals/calibration/claim_labels.csv"


def export(run_name: str | None, n: int, seed: int = 11) -> str:
    run_name = run_name or _latest_run()
    pool = {"supported": [], "unsupported": []}
    for row in _load_rows(run_name):
        claims = (row.get("judge_claims") or {}).get("faithfulness") or []
        evidence = "\n".join(row["pipeline"].get("prompt_contexts") or [])
        for k, c in enumerate(claims):
            verdict = "supported" if c["supported"] else "unsupported"
            pool[verdict].append({
                "claim_id": f"{row['id']}#{k}", "run_name": run_name, "item_id": row["id"],
                "question_type": row["question_type"], "question": row["question"],
                "claim": c["statement"], "judge_verdict": verdict,
                "judge_reason": c.get("judge_reason") or "", "evidence": evidence,
                "assistant_label": "", "assistant_note": "", "human_label": "", "human_note": ""})
    rng = random.Random(seed)
    picked = []
    for verdict in ("unsupported", "supported"):      # balance: judge errors on both sides
        rng.shuffle(pool[verdict])
        picked += pool[verdict][: n // 2]
    rng.shuffle(picked)
    out = repo_path(DEFAULT_FILE)
    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(picked)
    print(f"Wrote {len(picked)} claims ({sum(p['judge_verdict'] == 'unsupported' for p in picked)} judged "
          f"unsupported; pool: {len(pool['supported'])} supported / {len(pool['unsupported'])} unsupported) "
          f"to {out}")
    return str(out)


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    r = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return round((c - r) / d, 3), round((c + r) / d, 3)


def agreement(path: str | None, column: str) -> dict:
    path = path or str(repo_path(DEFAULT_FILE))
    with open(path, encoding="utf-8", newline="") as f:
        rows = [r for r in csv.DictReader(f) if r[f"{column}_label"].strip()]
    if not rows:
        # Agreement on zero labels is not a calibration result: write nothing.
        raise SystemExit(f"No {column} labels in {path} - fill {column}_label first "
                         "(python -m evals.human_review export / validate / merge).")
    bad =[r["claim_id"] for r in rows if r[f"{column}_label"].strip() not in LABELS]
    if bad:
        raise ValueError(f"invalid labels for {bad[:5]} - use one of {LABELS}")
    determinate = [r for r in rows if r[f"{column}_label"] != "indeterminate"]
    truth = [r[f"{column}_label"] == "supported" for r in determinate]
    judge = [r["judge_verdict"] == "supported" for r in determinate]
    n = len(determinate)
    agree = sum(t == j for t, j in zip(truth, judge))
    fn = sum(t and not j for t, j in zip(truth, judge))          # supported, judge said unsupported
    fp = sum((not t) and j for t, j in zip(truth, judge))        # unsupported/contradicted, judge said supported
    n_sup, n_unsup = sum(truth), n - sum(truth)
    po = agree / n if n else None
    pt, pj = (sum(truth) / n, sum(judge) / n) if n else (0, 0)
    pe = pt * pj + (1 - pt) * (1 - pj)
    kappa = round((po - pe) / (1 - pe), 3) if n and pe < 1 else None
    report = {
        "label_source": column, "labelled": len(rows), "indeterminate": len(rows) - n, "determinate": n,
        "accuracy": round(po, 3) if po is not None else None, "accuracy_ci95": wilson(agree, n),
        "cohen_kappa": kappa,
        "judge_false_negative_rate": round(fn / n_sup, 3) if n_sup else None,
        "fnr_ci95": wilson(fn, n_sup), "n_label_supported": n_sup,
        "judge_false_positive_rate": round(fp / n_unsup, 3) if n_unsup else None,
        "fpr_ci95": wilson(fp, n_unsup), "n_label_unsupported_or_contradicted": n_unsup,
        "contradicted": sum(1 for r in determinate if r[f"{column}_label"] == "contradicted"),
    }
    print(json.dumps(report, indent=1))
    if column != "human":
        print("NOTE: these are assistant (AI) labels - provisional evidence, not a human calibration.")
    out = repo_path(f"evals/calibration/claim_agreement_{column}.json")
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m evals.claim_calibration")
    sub = p.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export")
    e.add_argument("--run")
    e.add_argument("--n", type=int, default=60)
    a = sub.add_parser("agreement")
    a.add_argument("--file")
    a.add_argument("--labels", choices=["human", "assistant"], default="human")
    args = p.parse_args(argv)
    if args.cmd == "export":
        export(args.run, args.n)
    else:
        agreement(args.file, args.labels)
    return 0


if __name__ == "__main__":
    sys.exit(main())
