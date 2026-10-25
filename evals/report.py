"""Builds markdown tables for evals/REPORT.md from a run directory.

    python -m evals.report [--run RUN_NAME]   -> evals/runs/<run>/report_tables.md

Includes: scores vs thresholds, retrieval breakdowns (k = 1,3,5,10) by
question_type / service / severity, generation breakdowns, and the 10 worst
questions with an automatic retrieval-vs-generation diagnosis.
"""

import argparse
import json
import sys

from evals.calibration import _latest_run, _load_rows
from evals.run import NO_ANSWER_TYPES, check_gate
from evals.settings import load_config, load_thresholds, repo_path

RET_COLS = ["n", "hit_rate@1", "hit_rate@3", "hit_rate@5", "hit_rate@10", "recall@5", "recall@10",
            "precision@1", "precision@3", "precision@5", "mrr", "ndcg@3", "ndcg@5", "ndcg@10",
            "llm_context_hit", "llm_context_precision"]
GEN_COLS = ["n", "faithfulness", "faithfulness_full", "answer_relevancy", "context_precision",
            "context_recall", "answer_correctness", "correct_refusal"]


def _fmt(v):
    if v is None:
        return "–"
    return f"{v:.3f}" if isinstance(v, float) else str(v)


def table(rows: dict[str, dict], cols: list[str], first: str) -> str:
    present = [c for c in cols if any(c in r for r in rows.values())]
    out = [f"| {first} | " + " | ".join(present) + " |",
           "|" + "---|" * (len(present) + 1)]
    for name, r in rows.items():
        out.append(f"| {name} | " + " | ".join(_fmt(r.get(c)) for c in present) + " |")
    return "\n".join(out)


def badness(row: dict) -> float:
    if row["question_type"] in NO_ANSWER_TYPES:
        return (row.get("refusal") or {}).get("correct_refusal", 1.0)
    j = row.get("judge") or {}
    parts = [row["retrieval"]["metrics"].get("hit_rate@5"), j.get("faithfulness"),
             j.get("answer_correctness"), j.get("context_recall"), j.get("answer_relevancy")]
    parts = [p for p in parts if p is not None]
    return sum(parts) / len(parts) if parts else 1.0


def diagnose(row: dict) -> str:
    j = row.get("judge") or {}
    ret = row["retrieval"]
    ref = row.get("refusal") or {}
    p = row.get("pipeline") or {}
    matched = p.get("incident_ids") or []
    if row["question_type"] in NO_ANSWER_TYPES:
        if ref.get("asserted_root_cause"):
            if matched:
                return (f"**Evidence match check accepted {', '.join(matched)}** as describing the asked "
                        f"problem, so the model answered from them. Judge: {ref.get('reason')}")
            return f"**Generation asserted a cause without a matched incident.** Judge: {ref.get('reason')}"
        return f"Did not clearly decline. Judge: {ref.get('reason')}"
    expected = set(row["expected_chunk_ids"])
    relevant = set(ret.get("llm_context_ids") or [])
    ranks = {cid: i for i, cid in enumerate(ret["retrieved_ids"], start=1)}
    rank_txt = ", ".join(f"{e}@{ranks.get(e, '>10')}" for e in sorted(expected))
    if not expected <= relevant:
        missing = sorted(expected - relevant)
        return (f"**Retrieval failure:** expected {', '.join(missing)} did not pass the relevance filter "
                f"(ranks: {rank_txt}; top-1 was {ret['retrieved_ids'][0]}).")
    if not expected <= set(matched):
        return (f"**Evidence match-check miss:** retrieved ({rank_txt}) but not judged to describe the asked "
                f"problem (matched: {matched or 'none'}).")
    if ref.get("refused"):
        return (f"**Generation (declined):** evidence matched ({rank_txt}); status "
                f"{p.get('answer_status')}, contradictions: {p.get('contradictions') or 'none'}.")
    def low(name, cut):
        return j.get(name) is not None and j[name] < cut

    notes = []
    if low("faithfulness", 0.7):
        notes.append(f"unfaithful claims (faithfulness {j['faithfulness']:.2f}, "
                     f"full report {_fmt(j.get('faithfulness_full'))})")
    if low("answer_correctness", 0.5):
        notes.append(f"answer diverges from reference (correctness {j['answer_correctness']:.2f})")
    if low("answer_relevancy", 0.6):
        notes.append(f"low relevancy ({j['answer_relevancy']:.2f})")
    if low("context_recall", 0.5):
        notes.append(f"context recall {j['context_recall']:.2f} despite the expected record being present "
                     "(reference may contain details beyond the record)")
    rb = row.get("runbook_check") or {}
    if rb and not rb.get("match"):
        notes.append(f"runbook mis-selected ({rb.get('actual')} instead of {rb.get('expected')})")
    return (f"**Generation:** retrieval was correct ({rank_txt}); " + "; ".join(notes)
            if notes else f"Mixed/minor: retrieval ok ({rank_txt}).")


def build(run_name: str | None = None) -> str:
    cfg = load_config()
    run_name = run_name or _latest_run()
    run_dir = repo_path(f"{cfg['paths']['runs_dir']}/{run_name}/x").parent
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    rows = _load_rows(run_name)
    m = summary["metrics"]
    failed = {f.split(":")[0] for f in check_gate(m)}

    lines = [f"Run: `{run_name}`  ", f"Items: {summary['n_items']}  ",
             f"Pipeline config: `{json.dumps(summary['pipeline_config'])}`", "",
             "### Scores vs thresholds", "", "| metric | value | threshold | status |", "|---|---|---|---|"]
    for name, rule in load_thresholds().items():
        lines.append(f"| {name} | {_fmt(m.get(name))} | {rule['op']} {rule['value']} | "
                     f"{'❌ FAIL' if name in failed else '✅ PASS'} |")
    lines += ["", "### All headline metrics", "", "| metric | value |", "|---|---|"]
    lines += [f"| {k} | {_fmt(v)} |" for k, v in sorted(m.items())]

    ret = summary["retrieval"]
    lines += ["", "### Retrieval (overall, in-scope questions)", "",
              table({"overall": ret["overall"]}, RET_COLS, "set")]
    for key in ("question_type", "service", "severity", "doc_type"):
        groups = {g: v for g, v in ret[f"by_{key}"].items() if "mrr" in v}
        if groups:
            lines += ["", f"### Retrieval by {key}", "", table(groups, RET_COLS, key)]

    gen = summary.get("generation")
    if gen:
        for key in ("question_type", "service"):
            lines += ["", f"### Generation by {key}", "", table(gen[f"by_{key}"], GEN_COLS, key)]

    scored = [r for r in rows if r.get("refusal")]   # judged rows only (excludes fallbacks)
    worst = sorted(scored, key=badness)[:10]
    lines += ["", "### 10 worst questions", ""]
    for i, r in enumerate(worst, start=1):
        j = r.get("judge") or {}
        link = f" — [trace]({r['trace_url']})" if r.get("trace_url") else ""
        lines += [
            f"**{i}. [{r['question_type']}/{r.get('question_style')}] {r['question']}**{link}  ",
            f"expected: `{r['expected_chunk_ids']}` · top-5 retrieved: `{r['retrieval']['retrieved_ids'][:5]}` · "
            f"evidence strength: {r['pipeline']['evidence_strength']}  ",
            "scores: " + ", ".join(
                [f"{k}={_fmt(v)}" for k, v in j.items()]
                + ([f"refused={r['refusal']['refused']}, asserted_root_cause={r['refusal']['asserted_root_cause']}"]
                   if r["question_type"] in NO_ANSWER_TYPES else [])) + "  ",
            f"diagnosis: {diagnose(r)}", "",
        ]
    out = run_dir / "report_tables.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {out}")
    return str(out)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m evals.report")
    p.add_argument("--run")
    build(p.parse_args(argv).run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
