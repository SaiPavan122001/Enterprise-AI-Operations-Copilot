"""Step 6: judge calibration against human labels.

    python -m evals.calibration export [--run RUN_NAME]   # writes the CSV to label
    python -m evals.calibration agreement [--file CSV]     # after filling human_label

Each CSV row is one (question, metric) judgement, sampled evenly across the
LLM-judge metrics (RAGAS metrics + the refusal judge). Fill ``human_label``
with 1 (the answer deserves to pass this metric) or 0 (it should fail). A
fractional value in [0, 1] is also accepted. Rows left blank are ignored.

Agreement report: per metric and overall - accuracy of the binarised judge vs
human, Cohen's kappa, the judge's precision/recall at catching human "fail"
labels, and Spearman correlation between raw judge score and human label.
"""

import argparse
import csv
import json
import random
import sys
from collections import defaultdict

from evals.settings import load_config, repo_path

FIELDS = ["sample_id", "run_name", "item_id", "question_type", "metric", "question",
          "reference_answer", "retrieved_contexts", "answer_evaluated", "judge_score",
          "judge_pass", "judge_reason", "trace_url", "human_label", "human_notes"]


def _latest_run() -> str:
    runs = repo_path(load_config()["paths"]["runs_dir"] + "/x").parent
    return (runs / "LATEST").read_text(encoding="utf-8").strip()


def _load_rows(run_name: str) -> list[dict]:
    path = repo_path(f"{load_config()['paths']['runs_dir']}/{run_name}/results.jsonl")
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def export(run_name: str | None = None) -> str:
    from evals.judge import metric_inputs

    cfg = load_config()["calibration"]
    run_name = run_name or _latest_run()
    rows = _load_rows(run_name)
    rng = random.Random(load_config()["testset"]["seed"])

    pools: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        if not row.get("pipeline"):
            continue
        inputs = metric_inputs(row)
        for metric in cfg["metrics"]:
            value = (row.get("judge") or {}).get(metric)
            if value is None:
                continue
            inp = inputs[metric]
            pools[metric].append({
                "item_id": row["id"], "question_type": row["question_type"], "metric": metric,
                "question": row["question"], "reference_answer": row["reference_answer"],
                "retrieved_contexts": "\n---\n".join(inp.get("retrieved_contexts", [])),
                "answer_evaluated": inp.get("response", ""),
                "judge_score": round(value, 4),
                "judge_reason": (row.get("judge_reasons") or {}).get(metric) or "",
                "trace_url": row.get("trace_url") or "",
            })
        ref = row.get("refusal")
        if ref and row["question_type"] in ("out_of_scope", "permission"):
            pools["correct_refusal"].append({
                "item_id": row["id"], "question_type": row["question_type"],
                "metric": "correct_refusal", "question": row["question"],
                "reference_answer": row["reference_answer"],
                "retrieved_contexts": "\n---\n".join(row["pipeline"]["contexts"]),
                "answer_evaluated": row["pipeline"]["answer_core"],
                "judge_score": ref["correct_refusal"], "judge_reason": ref.get("reason") or "",
                "trace_url": row.get("trace_url") or "",
            })

    for pool in pools.values():
        rng.shuffle(pool)
    available = sum(len(p) for p in pools.values())
    target = min(cfg["n_samples"], available)
    picked: list[dict] = []
    order = sorted(pools)
    while len(picked) < target:            # round-robin keeps metrics balanced
        for metric in order:
            if pools[metric] and len(picked) < target:
                picked.append(pools[metric].pop())
    rng.shuffle(picked)

    out = repo_path(cfg["out_file"])
    with open(out, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for i, rec in enumerate(picked, start=1):
            writer.writerow(rec | {
                "sample_id": i, "run_name": run_name,
                "judge_pass": int(rec["judge_score"] >= cfg["binarize_at"]),
                "human_label": "", "human_notes": "",
            })
    print(f"Wrote {len(picked)} samples ({available} available) to {out}")
    return str(out)


def _kappa(a: list[int], b: list[int]) -> float | None:
    n = len(a)
    if n == 0:
        return None
    po = sum(x == y for x, y in zip(a, b)) / n
    pa, pb = sum(a) / n, sum(b) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    return round((po - pe) / (1 - pe), 4) if pe < 1 else None


def _stats(recs: list[dict], threshold: float) -> dict:
    from scipy.stats import spearmanr

    judge = [int(r["judge"] >= threshold) for r in recs]
    human = [int(r["human"] >= 0.5) for r in recs]
    n = len(recs)
    tp = sum(j == 0 and h == 0 for j, h in zip(judge, human))      # both say "fail"
    judge_fail = judge.count(0)
    human_fail = human.count(0)
    rho = None
    if n >= 3 and len({r["judge"] for r in recs}) > 1 and len({r["human"] for r in recs}) > 1:
        rho = round(float(spearmanr([r["judge"] for r in recs], [r["human"] for r in recs])[0]), 4)
    return {
        "n": n,
        "accuracy": round(sum(j == h for j, h in zip(judge, human)) / n, 4) if n else None,
        "cohen_kappa": _kappa(judge, human),
        "fail_precision": round(tp / judge_fail, 4) if judge_fail else None,
        "fail_recall": round(tp / human_fail, 4) if human_fail else None,
        "spearman": rho,
        "judge_pass_rate": round(sum(judge) / n, 4) if n else None,
        "human_pass_rate": round(sum(human) / n, 4) if n else None,
    }


def agreement(path: str | None = None) -> dict:
    cfg = load_config()["calibration"]
    path = path or str(repo_path(cfg["out_file"]))
    with open(path, "r", encoding="utf-8", newline="") as f:
        labelled = [r for r in csv.DictReader(f) if r["human_label"].strip() != ""]
    if not labelled:
        print("No human labels found - fill the human_label column (1 = pass, 0 = fail).")
        return {}
    recs = [{"metric": r["metric"], "judge": float(r["judge_score"]),
             "human": float(r["human_label"]), "row": r} for r in labelled]
    by_metric = defaultdict(list)
    for r in recs:
        by_metric[r["metric"]].append(r)

    report = {"overall": _stats(recs, cfg["binarize_at"])}
    report |= {m: _stats(rs, cfg["binarize_at"]) for m, rs in sorted(by_metric.items())}

    print(f"\nJudge vs human agreement ({len(recs)} labelled rows, judge pass >= {cfg['binarize_at']})")
    header = (f"{'metric':22s} {'n':>4s} {'acc':>7s} {'kappa':>7s} {'failP':>7s} {'failR':>7s} {'rho':>7s} "
              f"{'judge%':>7s} {'human%':>7s}")
    print(header)
    print("-" * len(header))
    for name, s in report.items():
        cells = [s[k] for k in ("accuracy", "cohen_kappa", "fail_precision", "fail_recall",
                                "spearman", "judge_pass_rate", "human_pass_rate")]
        print(f"{name:22s} {s['n']:>4d} " + " ".join(
            f"{c:>7.3f}" if isinstance(c, float) else f"{'-':>7s}" for c in cells))
    print("\nkappa: <0.2 poor, 0.2-0.4 fair, 0.4-0.6 moderate, 0.6-0.8 substantial, >0.8 near-perfect")

    disagreements = [r["row"] for r in recs
                     if int(r["judge"] >= cfg["binarize_at"]) != int(r["human"] >= 0.5)]
    if disagreements:
        print(f"\n{len(disagreements)} disagreements (sample_id / metric / judge -> human):")
        for r in disagreements[:25]:
            print(f"  #{r['sample_id']:>3} {r['metric']:20s} {r['judge_score']} -> {r['human_label']}  "
                  f"{r['question'][:70]}")
    out = repo_path(cfg["out_file"]).with_name("agreement_report.json")
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nSaved {out}")
    return report


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m evals.calibration")
    sub = p.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export")
    e.add_argument("--run")
    a = sub.add_parser("agreement")
    a.add_argument("--file")
    args = p.parse_args(argv)
    if args.cmd == "export":
        export(args.run)
    else:
        agreement(args.file)
    return 0


if __name__ == "__main__":
    sys.exit(main())
