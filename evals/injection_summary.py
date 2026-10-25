"""Print a compact comparison of injection_eval result files.

    python -m evals.injection_summary baseline baseline_det after after_det
"""

import json
import sys

from evals.settings import repo_path


def main(argv=None) -> int:
    labels = argv if argv is not None else sys.argv[1:]
    for split in ("dev", "heldout"):
        print(f"\n######## {split}")
        for label in labels:
            try:
                r = json.load(open(repo_path(f"evals/results/injection_eval_{label}_{split}.json"), encoding="utf-8"))
            except FileNotFoundError:
                continue
            d = r["detection"]
            print(f"[{label}] self_check={r['self_check']} live={r['live']} cache_hits={r['eval_cache_hits']} "
                  f"engines={d['engines']}")
            print(f"  detection: attacks {d['attacks'] - d['attacks_missed']}/{d['attacks']} "
                  f"(rate {d['detection_rate']}), benign blocked {d['benign_blocked']}/{d['benign']} "
                  f"(FPR {d['false_positive_rate']}), latency median {d['latency_ms_median']} ms "
                  f"p90 {d['latency_ms_p90']} ms")
            for cat, v in d["by_category"].items():
                print(f"    {cat:32s} blocked {v['blocked']}/{v['n']}")
            fp = r.get("full_path")
            if fp:
                for g in ("off", "on"):
                    s = fp[g]
                    print(f"  full path guardrails {g}: attacker won {s['attacker_won']}/{s['cases']} "
                          f"(ASR {s['attack_success_rate']}), surfaced {s['surfaced']}, "
                          f"median {s['latency_ms_median']} ms")
                    for k, v in s["by_carrier_or_category"].items():
                        print(f"    {k:24s} won {v['won']}/{v['cases']}")
                print(f"  not delivered (excluded): {fp['not_delivered']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
