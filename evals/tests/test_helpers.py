"""Unit tests for pure helpers: judge ID normalisation, quality filter, calibration stats."""

import pytest

from evals.calibration import _kappa, _stats
from evals.testset import normalize_ids, passes_filter

KNOWN = {"INC-001", "INC-007", "INC-012"}


def test_normalize_ids_handles_bare_numbers():
    assert normalize_ids([7, "12", "inc-001"], KNOWN) == ["INC-001", "INC-007", "INC-012"]
    # unknown numbers stay as-is so they count as a mismatch
    assert normalize_ids([105], KNOWN) == ["105"]
    assert normalize_ids(None, KNOWN) == []


def test_filter_single_chunk():
    item = {"question_type": "single_chunk", "expected_chunk_ids": ["INC-007"]}
    ok, _ = passes_filter(item, {"matching_ids": [7], "quality": 5, "reference_ok": True}, 4, KNOWN)
    assert ok
    ok, reason = passes_filter(item, {"matching_ids": [7, 12], "quality": 5, "reference_ok": True}, 4, KNOWN)
    assert not ok and "ambiguous" in reason
    ok, reason = passes_filter(item, {"matching_ids": [7], "quality": 3, "reference_ok": True}, 4, KNOWN)
    assert not ok and "quality" in reason


def test_filter_out_of_scope():
    item = {"question_type": "out_of_scope", "expected_chunk_ids": []}
    assert passes_filter(item, {"matching_ids": [], "quality": 4}, 4, KNOWN)[0]
    assert not passes_filter(item, {"matching_ids": ["INC-001"], "quality": 5}, 4, KNOWN)[0]


def test_kappa():
    assert _kappa([1, 0, 1, 0], [1, 0, 1, 0]) == 1.0
    assert _kappa([1, 1, 0, 0], [0, 0, 1, 1]) == -1.0
    assert _kappa([1, 1, 1, 1], [1, 1, 1, 1]) is None   # no variance


def test_stats_fail_detection():
    recs = [{"judge": 0.9, "human": 1}, {"judge": 0.2, "human": 0},
            {"judge": 0.3, "human": 1}, {"judge": 0.8, "human": 0}]
    s = _stats(recs, 0.5)
    assert s["accuracy"] == 0.5
    assert s["fail_precision"] == 0.5 and s["fail_recall"] == 0.5
    assert s["judge_pass_rate"] == pytest.approx(0.5)
