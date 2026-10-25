"""Step 3: retrieval metrics - pure code, no LLM.

Each test question is run through the production retriever
(``vector_store.search_service.search_incidents``) with ``limit=max_k``. The
ranked incident IDs are compared to ``expected_chunk_ids`` (binary relevance).

Definitions (R = expected IDs, L = ranked results):
  hit_rate@k   1 if any of R appears in L[:k]
  recall@k     |R ∩ L[:k]| / |R|
  precision@k  |R ∩ L[:k]| / k          (max is |R|/k, e.g. 0.2 at k=5 for 1 expected)
  mrr          1 / rank of first relevant item in L[:max_k], else 0
  ndcg@k       DCG / IDCG with gain 1/log2(rank+1)

We also report what the LLM *actually* sees: the production incident agent
keeps only the top 5 and drops hits below MIN_RELEVANCE_SCORE.
"""

import math
from collections import defaultdict
from statistics import mean

RANKING_TYPES = {"single_chunk", "multi_chunk", "sme"}


def hit_at_k(ranked: list[str], relevant: set[str], k: int) -> float:
    return 1.0 if any(r in relevant for r in ranked[:k]) else 0.0


def recall_at_k(ranked: list[str], relevant: set[str], k: int) -> float:
    if not relevant:
        return 0.0
    return len(relevant & set(ranked[:k])) / len(relevant)


def precision_at_k(ranked: list[str], relevant: set[str], k: int) -> float:
    return len(relevant & set(ranked[:k])) / k


def reciprocal_rank(ranked: list[str], relevant: set[str]) -> float:
    for i, r in enumerate(ranked, start=1):
        if r in relevant:
            return 1.0 / i
    return 0.0


def ndcg_at_k(ranked: list[str], relevant: set[str], k: int) -> float:
    dcg = sum(1.0 / math.log2(i + 1) for i, r in enumerate(ranked[:k], start=1) if r in relevant)
    ideal = sum(1.0 / math.log2(i + 1) for i in range(1, min(len(relevant), k) + 1))
    return dcg / ideal if ideal else 0.0


def score_ranking(ranked: list[str], relevant: set[str], k_values: list[int]) -> dict[str, float]:
    out: dict[str, float] = {"mrr": reciprocal_rank(ranked, relevant)}
    for k in k_values:
        out[f"hit_rate@{k}"] = hit_at_k(ranked, relevant, k)
        out[f"recall@{k}"] = recall_at_k(ranked, relevant, k)
        out[f"precision@{k}"] = precision_at_k(ranked, relevant, k)
        out[f"ndcg@{k}"] = ndcg_at_k(ranked, relevant, k)
    return out


def retrieve(question: str, max_k: int) -> list[dict]:
    """Call the real production retriever. Returns [{id, score}] ranked."""
    from vector_store.search_service import search_incidents

    points = search_incidents(query=question, limit=max_k)
    return [
        {"id": (p.payload or {}).get("incident_id"), "score": float(p.score)}
        for p in points
    ]


def effective_context(ranked: list[dict], top_k: int = 5) -> list[str]:
    """IDs the production incident agent passes to the LLM: the top 5 run
    through the production relevance filter (agents.incident_agent.select_relevant)."""
    from agents.incident_agent import select_relevant

    return select_relevant([(r["id"], r["score"]) for r in ranked[:top_k]])


def evaluate_item(item: dict, ranked: list[dict], k_values: list[int]) -> dict:
    ids = [r["id"] for r in ranked]
    relevant = set(item.get("expected_chunk_ids") or [])
    seen = effective_context(ranked)
    row: dict = {"retrieved_ids": ids, "retrieved_scores": [round(r["score"], 4) for r in ranked],
                 "llm_context_ids": seen}
    if item["question_type"] in RANKING_TYPES and relevant:
        row["metrics"] = score_ranking(ids, relevant, k_values)
        row["metrics"]["llm_context_hit"] = 1.0 if relevant & set(seen) else 0.0
        row["metrics"]["llm_context_precision"] = (
            len(relevant & set(seen)) / len(seen) if seen else 0.0
        )
    else:
        # Out-of-scope / permission questions: nothing should reach the LLM.
        row["metrics"] = {"oos_context_leak": 1.0 if seen else 0.0}
    restricted = set(item.get("restricted_chunk_ids") or [])
    if restricted:
        row["metrics"]["permission_leak"] = 1.0 if restricted & set(ids) else 0.0
    return row


def aggregate(rows: list[dict], group_keys: list[str]) -> dict:
    """Mean of every metric overall and per value of each group key."""
    def _mean_metrics(subset):
        acc: dict[str, list[float]] = defaultdict(list)
        for r in subset:
            for name, v in r["retrieval"]["metrics"].items():
                acc[name].append(v)
        return {name: round(mean(vs), 4) for name, vs in acc.items()} | {"n": len(subset)}

    out = {"overall": _mean_metrics([r for r in rows if r["question_type"] in RANKING_TYPES])}
    for key in group_keys:
        groups: dict[str, list] = defaultdict(list)
        for r in rows:
            groups[str(r.get(key))].append(r)
        out[f"by_{key}"] = {g: _mean_metrics(sub) for g, sub in sorted(groups.items())}
    return out
