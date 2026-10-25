"""Build an UNSEEN labelled set for the claim-support verifier (round 6).

    python -m evals.build_verifier_heldout

The template claims of evals/claim_verifier_eval.py are the development set:
rules were written while looking at them. This script rewrites every one of
them with an LLM in a different wording, instructed to keep the exact meaning
(negations, figures, quoted titles, the incident ID). The label is carried over
from the template (supported / unsupported), so labels stay "by construction"
- with one caveat: a rewrite can change the meaning. Rewrites that drop the
incident ID are discarded.

Written once to evals/testsets/claim_verifier_heldout_v1.jsonl (refuses to
overwrite); scored only in aggregate by ``python -m evals.claim_verifier_eval
--file ...``. Nobody tunes rules on it.
"""

import json
import sys
from concurrent.futures import ThreadPoolExecutor

from evals.llm import chat_json
from evals.settings import load_config, repo_path

OUT = "evals/testsets/claim_verifier_heldout_v1.jsonl"
PROMPT = """Rewrite the sentence below as an engineer would write it in an incident report.
Keep EXACTLY the same meaning: keep every negation, figure, quoted title, service name, severity and
the incident ID ({iid}); do not add or remove any fact; do not soften or strengthen it.
Use different wording and sentence structure from the original.

SENTENCE: {statement}

Return JSON: {{"rewrite": "..."}}"""


def main() -> int:
    out = repo_path(OUT)
    if out.exists():
        raise SystemExit(f"{out} exists - the held-out set is written once")
    from evals.claim_verifier_eval import build_cases, link_table

    incidents, links = link_table()
    cases = build_cases(incidents, links)
    model = load_config()["llm"]["generator_model"]

    def rewrite(c):
        data = chat_json([{"role": "user", "content": PROMPT.format(iid=c["incident_id"], statement=c["statement"])}],
                         model=model, temperature=0.7)
        text = str(data.get("rewrite") or "").strip()
        return dict(c, template=c["statement"], statement=text) if c["incident_id"] in text else None

    with ThreadPoolExecutor(8) as pool:
        rows = [r for r in pool.map(rewrite, cases) if r]
    with open(out, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"Wrote {len(rows)} rewritten claims ({len(cases) - len(rows)} discarded) to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
