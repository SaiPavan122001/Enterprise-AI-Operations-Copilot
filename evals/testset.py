"""Step 2: build, merge, and upload the evaluation test set.

    python -m evals.testset build [--overwrite]   # generate testset_<version>.jsonl
    python -m evals.testset merge-sme FILE        # merge hand-written questions
    python -m evals.testset upload                # push to a Langfuse Dataset

Item schema (one JSON object per line):
    id, question, reference_answer, expected_chunk_ids, source_doc, doc_type,
    service, severity, question_type, question_style, restricted_chunk_ids,
    quality, testset_version, origin

question_type is one of: single_chunk, multi_chunk, out_of_scope, permission, sme.
"""

import argparse
import hashlib
import json
import logging
import random
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from itertools import combinations

from evals.corpus import Chunk, load_chunks, stratified_sample
from evals.llm import chat_json, usage
from evals.settings import load_config, repo_path

logger = logging.getLogger("evals.testset")

SOURCE_FILE = "backend/data/incidents.json"
PERMISSION_FIELDS = ("access_level", "allowed_roles", "acl", "restricted", "visibility")

SYSTEM = (
    "You write evaluation questions for an AI root-cause-analysis copilot used by "
    "SRE/on-call engineers. It answers from an internal incident database. "
    "Return strict JSON only."
)


def _item_id(question: str) -> str:
    return "q-" + hashlib.sha1(question.strip().lower().encode("utf-8")).hexdigest()[:10]


def _norm(question: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", question.lower()).strip()


def corpus_listing(chunks: list[Chunk]) -> str:
    return "\n".join(c.describe() for c in chunks)


# --------------------------------------------------------------------------- generation

def gen_single(chunk: Chunk, style: str, instruction: str, model: str) -> dict | None:
    prompt = f"""Write ONE question about the incident record below, plus a reference answer.

INCIDENT RECORD:
{chunk.describe()}

QUESTION STYLE: {instruction}

Rules:
- The question must be answerable from this record alone and must identify THIS incident
  (not other incidents on the same service).
- The reference answer must be 1-2 sentences, grounded ONLY in the record, and must state
  the root cause (and the deployment ID when relevant).

Return JSON: {{"question": "...", "reference_answer": "..."}}"""
    data = chat_json([{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
                     model=model, temperature=0.7)
    if not data.get("question") or not data.get("reference_answer"):
        return None
    return {
        "question": data["question"].strip(),
        "reference_answer": data["reference_answer"].strip(),
        "expected_chunk_ids": [chunk.chunk_id],
        "source_doc": f"{SOURCE_FILE}#{chunk.chunk_id}",
        "doc_type": chunk.doc_type, "service": chunk.service, "severity": chunk.severity,
        "question_type": "single_chunk", "question_style": style,
    }


def gen_multi(pair: tuple[Chunk, Chunk], model: str) -> dict | None:
    a, b = pair
    prompt = f"""Write ONE question that can only be fully answered by combining BOTH incident
records below (e.g. comparing their causes, or asking about both problems together), plus a
reference answer.

RECORD A: {a.describe()}
RECORD B: {b.describe()}

Rules:
- Describe each incident specifically enough that no other incident would match.
- Do not ask "list all incidents on <service>" - other incidents may exist on that service.
- The reference answer (2-3 sentences) must state both root causes, grounded only in the records.

Return JSON: {{"question": "...", "reference_answer": "..."}}"""
    data = chat_json([{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
                     model=model, temperature=0.7)
    if not data.get("question") or not data.get("reference_answer"):
        return None
    return {
        "question": data["question"].strip(),
        "reference_answer": data["reference_answer"].strip(),
        "expected_chunk_ids": sorted([a.chunk_id, b.chunk_id]),
        "source_doc": f"{SOURCE_FILE}#{a.chunk_id},{b.chunk_id}",
        "doc_type": "incident",
        "service": a.service if a.service == b.service else "multiple",
        "severity": a.severity if a.severity == b.severity else "mixed",
        "question_type": "multi_chunk",
        "question_style": "same_service" if a.service == b.service else "cross_service",
    }


def gen_out_of_scope(chunks: list[Chunk], n: int, model: str, variant: str = "") -> list[dict]:
    services = sorted({c.service for c in chunks})
    prompt = f"""The copilot's incident database contains ONLY these records:
{corpus_listing(chunks)}

Write {2 * n + 6} realistic questions an on-call engineer might ask this copilot that the database
CANNOT answer. Mix two kinds:
- "near_miss" (about half): about a known service ({', '.join(services)}) but a failure mode
  that is NOT in any record (e.g. a different symptom or cause).
- "unrelated": about services, systems or topics that do not appear at all.
Do not ask about anything that any record answers, even partially.

Return JSON: {{"questions": [{{"question": "...", "kind": "near_miss|unrelated"}}]}}"""
    if variant:   # distinct prompt per batch (the response cache would otherwise repeat a batch)
        prompt += "\n\n" + variant
    data = chat_json([{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
                     model=model, temperature=0.8)
    items = []
    for q in data.get("questions", []):
        if not q.get("question"):
            continue
        items.append({
            "question": q["question"].strip(),
            "reference_answer": (
                "The available incident data does not contain information to answer this; "
                "the copilot should say the evidence is insufficient rather than give a root cause."
            ),
            "expected_chunk_ids": [], "source_doc": None, "doc_type": None,
            "service": "none", "severity": "none",
            "question_type": "out_of_scope", "question_style": q.get("kind", "unknown"),
        })
    return items


def gen_permission(chunks: list[Chunk], model: str) -> list[dict]:
    restricted = [c for c in chunks if any(f in c.payload for f in PERMISSION_FIELDS)]
    if not restricted:
        logger.info("No permission metadata on any record (checked %s) - "
                    "permission questions skipped; permission_leaks is not testable.",
                    ", ".join(PERMISSION_FIELDS))
        return []
    # Retained for when ACL metadata is added: ask about restricted records as an
    # unauthorized user; expected retrieval is nothing restricted.
    items = []
    for c in restricted:
        item = gen_single(c, "permission", "Ask directly about this incident.", model)
        if item:
            item.update(question_type="permission", expected_chunk_ids=[],
                        restricted_chunk_ids=[c.chunk_id], question_style="unauthorized_user")
            items.append(item)
    return items


# --------------------------------------------------------------------------- quality filter

def judge_quality(item: dict, chunks: list[Chunk], model: str) -> dict:
    prompt = f"""You are auditing an evaluation question for an incident-RCA copilot.

INCIDENT DATABASE (complete):
{corpus_listing(chunks)}

QUESTION: {item['question']}
PROPOSED REFERENCE ANSWER: {item['reference_answer']}

1. matching_ids: which record IDs are needed to answer the question? Use the exact ID strings
   shown in brackets, e.g. ["INC-007"]. Use [] if no record answers it. Include an ID only if
   the question clearly refers to that incident.
2. quality (1-5): is it a clear, specific, realistic question an engineer would ask?
   1 = vague/ambiguous/nonsensical, 5 = clear and specific.
3. reference_ok: is the reference answer correct and supported by the records (true/false)?

Return JSON: {{"matching_ids": [...], "quality": n, "reference_ok": true|false, "reason": "..."}}"""
    return chat_json([{"role": "user", "content": prompt}], model=model)


def normalize_ids(raw, known: set[str]) -> list[str]:
    """Judges sometimes answer 7 or "7" instead of "INC-007"."""
    out = set()
    for value in raw or []:
        s = str(value).strip().upper()
        if s not in known and s.isdigit() and f"INC-{int(s):03d}" in known:
            s = f"INC-{int(s):03d}"
        out.add(s)
    return sorted(out)


def passes_filter(item: dict, verdict: dict, min_quality: int, known: set[str]) -> tuple[bool, str]:
    quality = int(verdict.get("quality") or 0)
    found = normalize_ids(verdict.get("matching_ids"), known)
    if quality < min_quality:
        return False, f"quality {quality} < {min_quality}"
    if item["question_type"] in ("single_chunk", "multi_chunk"):
        if found != sorted(item["expected_chunk_ids"]):
            return False, f"ambiguous: judge matched {found}, expected {item['expected_chunk_ids']}"
        if not verdict.get("reference_ok", False):
            return False, "reference answer not supported"
    if item["question_type"] == "out_of_scope" and found:
        return False, f"not out of scope: judge matched {found}"
    return True, "ok"


# --------------------------------------------------------------------------- build / io

def testset_path(version: str | None = None):
    cfg = load_config()["testset"]
    return repo_path(f"{cfg['dir']}/testset_{version or cfg['version']}.jsonl")


def read_testset(version: str | None = None) -> list[dict]:
    path = testset_path(version)
    if not path.exists():
        raise FileNotFoundError(f"{path} not found - run `python -m evals.testset build`")
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_testset(items: list[dict], version: str, manifest: dict) -> None:
    path = testset_path(version)
    with open(path, "w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    with open(path.with_suffix(".manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    logger.info("Wrote %d items to %s", len(items), path)


def _finalize(item: dict, version: str, origin: str, quality=None) -> dict:
    item.setdefault("restricted_chunk_ids", [])
    item.update(id=_item_id(item["question"]), testset_version=version,
                origin=origin, quality=quality)
    return item


def build(overwrite: bool = False) -> list[dict]:
    cfg = load_config()
    tcfg, model = cfg["testset"], cfg["llm"]["generator_model"]
    version = tcfg["version"]
    if testset_path(version).exists() and not overwrite:
        raise SystemExit(f"{testset_path(version)} exists - bump testset.version or pass --overwrite")

    rng = random.Random(tcfg["seed"])
    chunks = load_chunks()
    sampled = stratified_sample(chunks, tcfg["stratify_by"], tcfg["max_chunks"], tcfg["seed"])
    logger.info("Sampled %d/%d records stratified by %s", len(sampled), len(chunks), tcfg["stratify_by"])

    jobs = [(gen_single, (c, style, instr, model))
            for c in sampled for style, instr in tcfg["single_chunk_styles"].items()]
    same = [p for p in combinations(sampled, 2) if p[0].service == p[1].service]
    cross = [p for p in combinations(sampled, 2) if p[0].service != p[1].service]
    rng.shuffle(same), rng.shuffle(cross)
    n_multi = tcfg["multi_chunk_count"]
    n_same = (n_multi + 1) // 2
    pairs = same[:n_same] + cross[: n_multi - n_same]
    # Over-generate multi-chunk 2x: the ambiguity filter rejects many pair questions.
    pairs += (same[n_same:] + cross[n_multi - n_same:])[:n_multi]
    jobs += [(gen_multi, (p, model)) for p in pairs]

    with ThreadPoolExecutor(cfg["llm"]["max_concurrency"]) as pool:
        candidates = [r for r in pool.map(lambda j: j[0](*j[1]), jobs) if r]
    candidates += gen_out_of_scope(chunks, tcfg["out_of_scope_count"], model)
    candidates += gen_permission(chunks, model)
    logger.info("Generated %d candidates; filtering...", len(candidates))

    with ThreadPoolExecutor(cfg["llm"]["max_concurrency"]) as pool:
        verdicts = list(pool.map(lambda it: judge_quality(it, chunks, cfg["llm"]["judge_model"]), candidates))

    known = {c.chunk_id for c in chunks}
    kept, rejected, seen = [], [], set()
    counts = {"multi_chunk": 0, "out_of_scope": 0}
    for item, verdict in zip(candidates, verdicts):
        ok, reason = passes_filter(item, verdict, tcfg["min_quality"], known)
        key = _norm(item["question"])
        if ok and key in seen:
            ok, reason = False, "duplicate"
        cap = {"multi_chunk": n_multi, "out_of_scope": tcfg["out_of_scope_count"]}.get(item["question_type"])
        if ok and cap is not None and counts[item["question_type"]] >= cap:
            ok, reason = False, "over quota"
        if ok:
            seen.add(key)
            if cap is not None:
                counts[item["question_type"]] += 1
            kept.append(_finalize(item, version, "generated", verdict.get("quality")))
        else:
            rejected.append({"question": item["question"], "type": item["question_type"],
                             "reason": reason, "judge": verdict.get("reason")})

    sme = load_sme(chunks, version)
    kept += [s for s in sme if _norm(s["question"]) not in seen]

    by_type: dict[str, int] = {}
    for it in kept:
        by_type[it["question_type"]] = by_type.get(it["question_type"], 0) + 1
    manifest = {
        "version": version, "created_at": datetime.now(timezone.utc).isoformat(),
        "generator_model": model, "judge_model": cfg["llm"]["judge_model"],
        "corpus_records": len(chunks), "sampled_records": len(sampled),
        "candidates": len(candidates), "kept": len(kept), "by_type": by_type,
        "rejected": rejected,
    }
    write_testset(kept, version, manifest)
    logger.info("Kept %d / rejected %d. By type: %s. Generator cost so far: $%.4f",
                len(kept), len(rejected), by_type, usage.cost_usd())
    return kept


# --------------------------------------------------------------------------- SME merge

def load_sme(chunks: list[Chunk], version: str, path=None) -> list[dict]:
    """Normalise a hand-written JSONL file. Required: question. Optional:
    reference_answer, expected_chunk_ids, question_type, source_doc."""
    path = path or repo_path(load_config()["testset"]["sme_file"])
    if not path.exists():
        return []
    by_id = {c.chunk_id: c for c in chunks}
    items = []
    with open(path, "r", encoding="utf-8") as f:
        for n, line in enumerate(f, start=1):
            if not line.strip() or line.lstrip().startswith("//"):
                continue
            raw = json.loads(line)
            if not raw.get("question"):
                raise ValueError(f"{path}:{n} has no 'question'")
            expected = raw.get("expected_chunk_ids") or []
            unknown = [e for e in expected if e not in by_id]
            if unknown:
                raise ValueError(f"{path}:{n} references unknown chunk IDs {unknown}")
            qtype = raw.get("question_type") or ("sme" if expected else "out_of_scope")
            first = by_id.get(expected[0]) if expected else None
            items.append(_finalize({
                "question": raw["question"].strip(),
                "reference_answer": raw.get("reference_answer", ""),
                "expected_chunk_ids": expected,
                "source_doc": raw.get("source_doc") or (
                    f"{SOURCE_FILE}#{','.join(expected)}" if expected else None),
                "doc_type": "incident" if expected else None,
                "service": first.service if first else "none",
                "severity": first.severity if first else "none",
                "question_type": qtype, "question_style": raw.get("question_style", "sme"),
                "restricted_chunk_ids": raw.get("restricted_chunk_ids", []),
            }, version, "sme"))
    logger.info("Loaded %d SME questions from %s", len(items), path)
    return items


def merge_sme(path: str) -> None:
    from pathlib import Path

    version = load_config()["testset"]["version"]
    items = read_testset(version)
    sme = load_sme(load_chunks(), version, Path(path))
    existing = {it["id"] for it in items}
    added = [s for s in sme if s["id"] not in existing]
    manifest_path = testset_path(version).with_suffix(".manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    manifest.setdefault("merged_sme", []).append(
        {"file": str(path), "added": len(added), "at": datetime.now(timezone.utc).isoformat()})
    write_testset(items + added, version, manifest)
    logger.info("Merged %d new SME questions (%d already present)", len(added), len(sme) - len(added))


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(name)s | %(message)s")
    parser = argparse.ArgumentParser(prog="python -m evals.testset")
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--overwrite", action="store_true")
    m = sub.add_parser("merge-sme")
    m.add_argument("file")
    sub.add_parser("upload")
    args = parser.parse_args(argv)

    if args.cmd == "build":
        build(args.overwrite)
    elif args.cmd == "merge-sme":
        merge_sme(args.file)
    elif args.cmd == "upload":
        from evals.langfuse_io import upload_dataset

        upload_dataset(read_testset())
    return 0


if __name__ == "__main__":
    sys.exit(main())
