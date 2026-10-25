"""Read-only access to the records stored in the production Qdrant collection.

A "chunk" here is one Qdrant point (the copilot embeds one point per
incident, with no further chunking). The chunk ID used throughout the evals is the
payload's ``incident_id``, which is stable: the point ID is
``uuid5(namespace, incident_id)`` (backend/scripts/seed.py).
"""

import random
from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class Chunk:
    chunk_id: str          # incident_id
    point_id: str
    doc_type: str          # always "incident" for this corpus
    service: str
    severity: str
    status: str
    title: str
    root_cause: str
    deployment_id: str | None
    payload: dict = field(default_factory=dict)

    @property
    def text(self) -> str:
        # Mirrors the embedded text in backend/scripts/seed.py.
        return f"Service: {self.service}\nTitle: {self.title}\nRoot Cause: {self.root_cause}"

    def describe(self) -> str:
        return (f"[{self.chunk_id}] service={self.service} severity={self.severity} "
                f"status={self.status} title=\"{self.title}\" root_cause=\"{self.root_cause}\" "
                f"deployment={self.deployment_id}")


def load_chunks() -> list[Chunk]:
    from config import settings
    from vector_store.qdrant_client import client

    chunks: list[Chunk] = []
    offset = None
    while True:
        points, offset = client.scroll(
            collection_name=settings.QDRANT_COLLECTION,
            limit=256, offset=offset, with_payload=True, with_vectors=False,
        )
        for p in points:
            pl = p.payload or {}
            chunks.append(Chunk(
                chunk_id=pl["incident_id"], point_id=str(p.id), doc_type="incident",
                service=pl.get("service", ""), severity=pl.get("severity", ""),
                status=pl.get("status", ""), title=pl.get("title", ""),
                root_cause=pl.get("root_cause", ""), deployment_id=pl.get("deployment_id"),
                payload=pl,
            ))
        if offset is None:
            break
    if not chunks:
        raise RuntimeError("Qdrant collection is empty - run `python -m scripts.seed` in backend/")
    return sorted(chunks, key=lambda c: c.chunk_id)


def stratified_sample(chunks: list[Chunk], by: str, n: int | None, seed: int) -> list[Chunk]:
    """Round-robin across strata (e.g. service) so every group is represented
    before any group gets a second record."""
    rng = random.Random(seed)
    groups: dict[str, list[Chunk]] = defaultdict(list)
    for c in chunks:
        groups[str(getattr(c, by))].append(c)
    for g in groups.values():
        rng.shuffle(g)
    order = sorted(groups)
    picked: list[Chunk] = []
    limit = len(chunks) if n is None else min(n, len(chunks))
    while len(picked) < limit:
        for key in order:
            if groups[key] and len(picked) < limit:
                picked.append(groups[key].pop())
    return picked
