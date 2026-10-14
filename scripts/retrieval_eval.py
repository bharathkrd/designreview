"""
Measure standards retrieval on the hand-labelled queries in packs/designreview/retrieval.toml.

    python scripts/retrieval_eval.py            # table: each retrieval aid on its own and together
    python scripts/retrieval_eval.py --check    # exit 1 if the configuration the agent uses falls
                                                # below the [floors] in retrieval.toml (CI)

Offline: the standards come from the captured fixtures (agentkit.sim), through the same
paging and the same recall_standards() the agent's action uses. Ranked ids are the
standards' base names (lower case), the unit the labels use.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agentkit.retrieval import evaluate  # noqa: E402
from agentkit.sim import SimPlatform  # noqa: E402
from packs.designreview.actions import _all_rows, recall_standards, retrieval_settings  # noqa: E402

FIXTURES = ROOT / "packs" / "designreview" / "fixtures"
VARIANTS = {
    "baseline (BM25 only)": dict(context=False, expand=False, gate=False),
    "+ context prefix": dict(context=True, expand=False, gate=False),
    "+ synonyms": dict(context=False, expand=True, gate=False),
    "+ relevance gate": dict(context=False, expand=False, gate=True),
    "all three (what the agent uses)": dict(context=True, expand=True, gate=True),
}
USED = "all three (what the agent uses)"


def standards(tenant: str) -> List[dict]:
    return _all_rows(SimPlatform(FIXTURES / f"{tenant}.json"), "DesignStandard.list", {})


def run(settings: Dict) -> Dict[str, Dict]:
    rows = {t: standards(t) for t in {q["tenant"] for q in settings["qrels"]}}
    table: Dict[str, Dict] = {}
    for label, flags in VARIANTS.items():
        pairs, per_query = [], []
        for q in settings["qrels"]:
            got = recall_standards(rows[q["tenant"]], q["query"], settings=settings, **flags)
            ranked = [m["name"].split("—")[0].strip().lower() for m in got["matches"]]
            relevant = {r.lower() for r in q["relevant"]}
            pairs.append((ranked, relevant))
            per_query.append((q["task"], ranked))
        table[label] = {**evaluate(pairs, k=int(settings.get("top_k", 5))), "ranked": per_query}
    return table


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--check", action="store_true", help="fail if the agent's configuration is below the floors")
    ap.add_argument("--verbose", action="store_true", help="also print what each query recalled")
    args = ap.parse_args(argv)
    settings = retrieval_settings()
    table = run(settings)
    k = int(settings.get("top_k", 5))
    print(f"Standards retrieval on {len(settings['qrels'])} labelled queries\n")
    print(f"| Configuration | recall@{k} | precision@{k} | MRR |\n|---|---|---|---|")
    for label, m in table.items():
        print(f"| {label} | {m[f'recall@{k}']:.2f} | {m[f'precision@{k}']:.2f} | {m['mrr']:.2f} |")
    if args.verbose:
        for label, m in table.items():
            print(f"\n{label}:")
            for task, ranked in m["ranked"]:
                print(f"  {task}: {ranked}")
    if not args.check:
        return 0
    floors = settings.get("floors") or {}
    used = table[USED]
    low = [f"{name} {used[name]:.2f} < {floor}" for name, floor in floors.items() if used.get(name, 0) < floor]
    print("\nfloors: " + ("ok" if not low else "BELOW: " + "; ".join(low)))
    return 1 if low else 0


if __name__ == "__main__":
    sys.exit(main())
