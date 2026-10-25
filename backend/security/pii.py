"""PII and secret redaction (Microsoft Presidio, with a regex fallback).

Redacted: people's names (PERSON), e-mail addresses, phone numbers, credit
cards, US SSNs, IBANs, credentials ("password=...", "token: ..."), API keys
and tokens (OpenAI/Google/GitHub/AWS/Slack/Langfuse/JWT/Bearer) and employee
IDs. Replaced by ``<ENTITY_TYPE>`` placeholders.

Deliberately NOT redacted, because investigations need them: service names,
incident/deployment/log IDs, timestamps, hostnames, URLs and IP addresses.

Where it is applied:
  * the question, before any LLM call, log line, trace or cache entry;
  * every text field of the generated answer, except values that occur in the
    authorized evidence records (``keep``) - evidence is never destroyed;
  * audit events; log lines (regex patterns only, in utils/log_context.py).

Engine: ``PII_ENGINE=presidio`` (default; spaCy ``PII_SPACY_MODEL``) |
``regex`` (no NLP model: no PERSON detection) | ``off``. If Presidio cannot
load, the regex engine is used and ``engine_status()`` reports it.
"""

import logging
import re
import threading
from collections.abc import Container
from functools import lru_cache

from config import settings

logger = logging.getLogger(__name__)

ENTITIES = ["PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD", "US_SSN", "IBAN_CODE",
            "CREDENTIAL", "API_KEY", "EMPLOYEE_ID"]

PATTERNS: dict[str, list[str]] = {
    "CREDENTIAL": [r"(?i)\b(?:password|passwd|pwd|passcode|secret|api[_-]?key|access[_-]?token|auth[_-]?token)"
                   r"\s*(?:[:=]|\bis\b)\s*\S+"],
    "API_KEY": [r"\bsk-[A-Za-z0-9_-]{16,}", r"\bAIza[0-9A-Za-z_-]{30,}", r"\bgh[pousr]_[A-Za-z0-9]{30,}",
                r"\bAKIA[0-9A-Z]{16}\b", r"\bxox[abpr]-[A-Za-z0-9-]{10,}", r"\b[ps]k-lf-[0-9a-f-]{16,}",
                r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}",
                r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}"],
    "EMPLOYEE_ID": [r"(?i)\b(?:employee|emp|staff)\s*(?:id|no\.?|number|#)?\s*[:#]?\s*\d{3,}\b"],
    "EMAIL_ADDRESS": [r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"],
    "PHONE_NUMBER": [r"(?<![\w-])(?:\+?\d{1,3}[\s.-])?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}\b"],
    "US_SSN": [r"\b\d{3}-\d{2}-\d{4}\b"],
    # card-shaped digit groups only (timestamps like 2026-05-14 10:00 never match), then Luhn
    "CREDIT_CARD": [r"\b\d{4}[ -]?\d{4}[ -]?\d{4}[ -]?\d{1,7}\b"],
}
# Patterns Presidio's own recognizers do not cover (it has e-mail, phone, card, SSN, IBAN).
CUSTOM = ("CREDENTIAL", "API_KEY", "EMPLOYEE_ID")
_COMPILED = {k: [re.compile(p) for p in v] for k, v in PATTERNS.items()}
_ID_RE = re.compile(r"\b(?:INC|DEP|LOG)-\d+\b")

_engine = None
_engine_error: str | None = None
_lock = threading.Lock()


def _luhn(digits: str) -> bool:
    d = [int(c) for c in digits if c.isdigit()]
    if not 13 <= len(d) <= 19:
        return False
    # double every second digit counted from the right (index parity == length parity)
    total = sum((x * 2 - 9 if x * 2 > 9 else x * 2) if i % 2 == len(d) % 2 else x for i, x in enumerate(d))
    return total % 10 == 0


@lru_cache(maxsize=1)
def domain_vocabulary() -> frozenset[str]:
    """Words of this system's own records (service names, incident titles and causes,
    deployment changes, runbook names). spaCy's small model sometimes tags such words
    as PERSON; a PERSON finding made only of these words is not a person."""
    from utils.data_store import get_deployments, get_incidents, get_runbooks

    text = " ".join([f"{i.get('service')} {i.get('title')} {i.get('root_cause')}" for i in get_incidents()]
                    + [f"{d.get('service')} {d.get('change')}" for d in get_deployments()]
                    + list(get_runbooks()))
    return frozenset(w for w in re.findall(r"[a-z0-9_]+", text.lower()) if len(w) > 2) | _NOT_PERSONS


# Report headings and common infrastructure product names that spaCy's small model
# tags as PERSON (measured on this project's questions and answers).
_NOT_PERSONS = frozenset("""root cause summary impact evidence conclusions contributing factors hypotheses
unknowns recommended remediation preventive actions confidence investigation details monitor lambda kafka redis
jenkins grafana kibana prometheus docker kubernetes helm terraform ansible nginx postgres mysql oracle mongo
elasticsearch airflow celery rabbitmq sentry datadog splunk okta azure aws gcp vault consul envoy istio""".split())


def _not_a_person(value: str, vocab: frozenset[str]) -> bool:
    if "\n" in value or "-" in value or _ID_RE.search(value):
        return True
    tokens = re.findall(r"[A-Za-z0-9_]+", value)
    if not tokens:
        return True
    words = [t.lower() for t in tokens]
    # all-caps acronyms (SMTP, ETL) and system vocabulary are not names
    return all(w in vocab or t.isupper() for t, w in zip(tokens, words))


def _load_presidio():
    logging.getLogger("presidio-analyzer").setLevel(logging.WARNING)
    from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer
    from presidio_analyzer.nlp_engine import NlpEngineProvider

    nlp = NlpEngineProvider(nlp_configuration={
        "nlp_engine_name": "spacy", "models": [{"lang_code": "en", "model_name": settings.PII_SPACY_MODEL}],
    }).create_engine()
    engine = AnalyzerEngine(nlp_engine=nlp, supported_languages=["en"])
    for entity in CUSTOM:
        patterns = [Pattern(f"{entity}_{n}", p, 0.9) for n, p in enumerate(PATTERNS[entity])]
        engine.registry.add_recognizer(PatternRecognizer(supported_entity=entity, patterns=patterns))
    return engine


def engine():
    global _engine, _engine_error
    if settings.PII_ENGINE != "presidio":
        return None
    with _lock:
        if _engine is None and _engine_error is None:
            try:
                _engine = _load_presidio()
            except Exception as exc:          # package or spaCy model missing
                _engine_error = type(exc).__name__
                logger.error("Presidio unavailable (%s) - using regex PII redaction (no PERSON detection)",
                             _engine_error)
    return _engine


def engine_status() -> str:
    if settings.PII_ENGINE == "off":
        return "off"
    if settings.PII_ENGINE == "regex":
        return "regex"
    return "presidio" if engine() is not None else f"regex (presidio unavailable: {_engine_error})"


def find(text: str) -> list[tuple[int, int, str]]:
    """(start, end, entity) spans of PII / secrets in ``text``."""
    if not text or settings.PII_ENGINE == "off":
        return []
    spans: list[tuple[int, int, str]] = []
    eng = engine()
    if eng is not None:
        vocab = domain_vocabulary()
        for r in eng.analyze(text=text, language="en", entities=ENTITIES, score_threshold=0.4):
            value = text[r.start:r.end]
            if r.entity_type == "PERSON" and _not_a_person(value, vocab):
                continue
            spans.append((r.start, r.end, r.entity_type))
    # Regex patterns always run too: they are the floor if Presidio misses a format.
    for entity, regs in _COMPILED.items():
        for rx in regs:
            for m in rx.finditer(text):
                if entity == "CREDIT_CARD" and not _luhn(m.group()):
                    continue
                if _ID_RE.search(m.group()):
                    continue
                spans.append((m.start(), m.end(), entity))
    # merge overlaps, keep the longest
    spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))
    merged: list[tuple[int, int, str]] = []
    for s in spans:
        if merged and s[0] < merged[-1][1]:
            if s[1] > merged[-1][1]:
                merged[-1] = (merged[-1][0], s[1], merged[-1][2])
            continue
        merged.append(s)
    return merged


def redact_text(text: str, keep: Container[str] = frozenset()) -> str:
    """Replace PII/secrets with <ENTITY>; values occurring in ``keep`` (authorized
    evidence text, lower-cased) are left intact."""
    if not text or not isinstance(text, str):
        return text
    out, last = [], 0
    for start, end, entity in find(text):
        value = text[start:end]
        if value.lower() in keep:
            continue
        out.append(text[last:start])
        out.append(f"<{entity}>")
        last = end
    out.append(text[last:])
    return "".join(out)


def redact_payload(obj, keep: Container[str] = frozenset(), skip_keys: tuple[str, ...] = ()):
    """Deep-redact every string in a JSON-like structure (keys in ``skip_keys`` untouched)."""
    if isinstance(obj, str):
        return redact_text(obj, keep)
    if isinstance(obj, dict):
        return {k: (v if k in skip_keys else redact_payload(v, keep, skip_keys)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact_payload(v, keep, skip_keys) for v in obj]
    return obj


def evidence_keep_set(evidence_texts: list[str]) -> "EvidenceText":
    """Lower-cased evidence text, for "keep" checks (a PII-looking value that is part of
    an authorized record - e.g. an on-call contact in a runbook - is not removed)."""
    return EvidenceText(" \n ".join(t for t in evidence_texts if t).lower())


class EvidenceText:
    """``value in keep`` means: the value occurs somewhere in the evidence text."""

    def __init__(self, text: str):
        self._text = text

    def __contains__(self, value: object) -> bool:
        return isinstance(value, str) and bool(value) and value in self._text
