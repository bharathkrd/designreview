"""
Check the pack's playbooks against its plans, routes, tasks and captured seat catalogues.

    python scripts/playbooks_check.py           # exit 1 on any problem (CI)
    python scripts/playbooks_check.py --write   # also rewrite the index in the playbooks README

Offline: the seat catalogues are the `tools` lists of the captured fixtures, one per tenant.
See agentkit/playbooks.py for what each status claims and what is checked.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agentkit.config import default_pack, read_config  # noqa: E402
from agentkit.playbooks import (check_constants, check_playbooks, load_constants, load_playbooks,  # noqa: E402
                                unverified, with_index)
from agentkit.registry import load_pack  # noqa: E402


def catalogs(fixtures_dir: Path) -> dict:
    out = {}
    for path in sorted(fixtures_dir.glob("*.json")):
        tools = json.loads(path.read_text(encoding="utf-8")).get("tools") or []
        out[path.stem] = {t if isinstance(t, str) else t.get("name") for t in tools}
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--pack", default=default_pack())
    ap.add_argument("--write", action="store_true", help="rewrite the index in the playbooks README")
    args = ap.parse_args(argv)

    reg = load_pack(args.pack)
    x = reg.extras
    pb_dir = Path(x["playbooks_dir"])
    books = load_playbooks(pb_dir)
    tasks = {p.stem: read_config(p) for p in sorted(Path(x["tasks_dir"]).glob("*.toml"))}
    plans = [p.stem for p in Path(x["plans_dir"]).glob("*.toml")]
    problems = check_playbooks(books, plans=plans, tasks=tasks, catalogs=catalogs(Path(x["fixtures_dir"])),
                               router=x["router"])

    readme = pb_dir / "README.md"
    current = readme.read_text(encoding="utf-8")
    wanted = with_index(current, books)
    if wanted != current:
        if args.write:
            readme.write_text(wanted, encoding="utf-8")
            print(f"rewrote the index in {readme.relative_to(ROOT).as_posix()}")
        else:
            problems.append(f"{readme.relative_to(ROOT).as_posix()}: index is stale "
                            "(run scripts/playbooks_check.py --write)")

    constants = load_constants(pb_dir / "constants.toml")
    problems += check_constants(constants, ROOT)

    counts = {s: sum(b.status == s for b in books) for s in ("live", "blocked", "spec")}
    print(f"{len(books)} playbooks ({counts['live']} live, {counts['blocked']} blocked, {counts['spec']} spec only), "
          f"{len(tasks)} tasks, {len(plans)} plans, {len(constants)} constants "
          f"({len(unverified(constants))} not yet checked against their source)")
    for p in problems:
        print(f"PROBLEM  {p}")
    print("ok" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
