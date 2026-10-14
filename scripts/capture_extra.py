"""
Add recorded calls to an existing platform fixture without re-capturing it.

    python scripts/capture_extra.py --tenant suryodaya --list DesignFile.list

Pages the given `.list` tool on the LIVE tenant (read-only) through the same read_all
the agent uses, records every exchange (agentkit.sim.fixture.RecordingSeat) and
appends the records that are not in packs/designreview/fixtures/<tenant>.json yet.
Existing records are never changed, so every task's replay stays exactly as it was.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agentkit.sim.fixture import RecordedCall, RecordingSeat, SeatFixture, _Recorder  # noqa: E402
from agentkit.transport import SeatRpcClient  # noqa: E402
from agentkit.transport.safe_reads import read_all  # noqa: E402

FIXTURES = ROOT / "packs" / "designreview" / "fixtures"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--tenant", required=True)
    ap.add_argument("--list", action="append", required=True, help="a .list tool to page in full (repeatable)")
    args = ap.parse_args(argv)
    path = FIXTURES / f"{args.tenant}.json"
    fixture = SeatFixture.load(path)
    known = set(fixture.index())
    rec = _Recorder()
    client = SeatRpcClient.for_tenant(args.tenant)
    client.initialize()
    seat = RecordingSeat(client, rec)
    for tool in args.list:
        rows = read_all(seat, tool, {})["data"]
        print(f"{args.tenant}: {tool}: {len(rows)} rows")
    added = [c for key, c in rec.calls.items() if key not in known]
    fixture.calls.extend(RecordedCall(**c.model_dump()) for c in added)
    fixture.note = (fixture.note + f"; +{len(added)} call(s) via scripts/capture_extra.py").strip("; ")
    fixture.save(path)
    print(f"appended {len(added)} new call record(s) to {path.name}; {len(rec.calls) - len(added)} already there")
    return 0


if __name__ == "__main__":
    sys.exit(main())
