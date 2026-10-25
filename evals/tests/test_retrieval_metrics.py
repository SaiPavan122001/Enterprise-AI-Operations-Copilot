"""Unit tests for the pure retrieval metrics (no Qdrant, no LLM)."""

import math

import pytest

from evals.retrieval import (
    hit_at_k, ndcg_at_k, precision_at_k, recall_at_k, reciprocal_rank, score_ranking,
)

RANKED = ["A", "B", "C", "D", "E"]


def test_hit_rate():
    assert hit_at_k(RANKED, {"C"}, 2) == 0.0
    assert hit_at_k(RANKED, {"C"}, 3) == 1.0


def test_recall_and_precision_multi_relevant():
    rel = {"B", "E"}
    assert recall_at_k(RANKED, rel, 1) == 0.0
    assert recall_at_k(RANKED, rel, 2) == 0.5
    assert recall_at_k(RANKED, rel, 5) == 1.0
    assert precision_at_k(RANKED, rel, 2) == 0.5
    assert precision_at_k(RANKED, rel, 5) == 0.4


def test_mrr():
    assert reciprocal_rank(RANKED, {"A"}) == 1.0
    assert reciprocal_rank(RANKED, {"C", "E"}) == pytest.approx(1 / 3)
    assert reciprocal_rank(RANKED, {"Z"}) == 0.0


def test_ndcg():
    assert ndcg_at_k(RANKED, {"A"}, 5) == 1.0
    # single relevant item at rank 2: (1/log2(3)) / 1
    assert ndcg_at_k(RANKED, {"B"}, 5) == pytest.approx(1 / math.log2(3))
    # two relevant at ranks 1 and 3; ideal is ranks 1 and 2
    expected = (1 + 1 / math.log2(4)) / (1 + 1 / math.log2(3))
    assert ndcg_at_k(RANKED, {"A", "C"}, 5) == pytest.approx(expected)
    assert ndcg_at_k(RANKED, {"Z"}, 5) == 0.0


def test_score_ranking_keys():
    out = score_ranking(RANKED, {"B"}, [1, 3])
    assert set(out) == {"mrr", "hit_rate@1", "recall@1", "precision@1", "ndcg@1",
                        "hit_rate@3", "recall@3", "precision@3", "ndcg@3"}
