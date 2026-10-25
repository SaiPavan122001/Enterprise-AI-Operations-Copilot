"""Regression gate: the retrieval-only (no API keys) run is gated on retrieval metrics only."""

from evals.run import check_gate, gated_thresholds
from evals.settings import load_thresholds

RETRIEVAL_OK = {"hit_rate@5": 1.0, "permission_leaks": 0}


def test_full_run_requires_every_metric():
    failures = check_gate(RETRIEVAL_OK)
    assert any(f.startswith("faithfulness: missing") for f in failures)
    assert set(gated_thresholds()) == set(load_thresholds())


def test_retrieval_only_run_skips_llm_metrics_but_still_gates_retrieval():
    assert check_gate(RETRIEVAL_OK, retrieval_only=True) == []
    assert set(gated_thresholds(retrieval_only=True)) == {"hit_rate@5", "permission_leaks"}
    failures = check_gate({"hit_rate@5": 0.9, "permission_leaks": 1}, retrieval_only=True)
    assert len(failures) == 2


def test_no_threshold_is_lowered_by_the_mode_flag():
    for name, rule in load_thresholds().items():
        if not rule.get("requires_llm"):
            assert gated_thresholds(retrieval_only=True)[name] == rule
