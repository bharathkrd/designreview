"""
Pre-flight: is the live seat still the platform our fixtures and tasks assume?

    python -m agentkit.harness.preflight [--pack packs.<name>] [--tenant <tenant>] [--fixture <file.json>]

Read-only. Logs in, reads tools/list, and reports:
- PROBLEM  a tool the pack depends on (registry.extras["required_tools"]) is
           missing, or now requires an argument the pack doesn't send;
- WARNING  the catalogue fingerprint differs from the fixture's (the platform
           added, removed or changed tools since capture): offline replays
           still run, but re-capture the fixture
           (python -m agentkit.sim.capture --tenant <tenant>).
Exit 1 on any problem, 0 otherwise (warnings included).

Provenance: the pre-flight idea (compare the live tool-catalogue hash with
the one recorded in the fixture, and check the tools the agent depends on
before a run) is referred from an outside source and rebuilt here.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from agentkit.config import default_pack, default_tenant
from agentkit.registry import Registry, load_pack
from agentkit.transport.catalog import ToolCatalog


def assess(catalog: ToolCatalog, registry: Registry, fixture: Optional[Dict[str, Any]]) -> Tuple[List[str], List[str]]:
    """(problems, warnings) for a live catalogue against the pack and a fixture."""
    problems = catalog.check_requirements(registry.extras.get("required_tools") or {})
    warnings: List[str] = []
    if fixture is not None:
        recorded = fixture.get("tools_fingerprint") or ""
        if not recorded:
            warnings.append("the fixture records no tool fingerprint (captured before 2026-10-12): re-capture it")
        elif recorded != catalog.fingerprint():
            live = catalog.names
            was = set(fixture.get("tools") or [])
            added, removed = sorted(live - was), sorted(was - live)
            detail = "; ".join(x for x in (f"added {added[:10]}" if added else "",
                                            f"removed {removed[:10]}" if removed else "") if x)
            warnings.append(f"tool catalogue changed since the fixture (fixture {recorded}, live "
                            f"{catalog.fingerprint()}{'; ' + detail if detail else '; schemas changed'}): re-capture it")
    return problems, warnings


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Check the live seat against the pack and its fixture (read-only).")
    ap.add_argument("--pack", default=None, help="default: config/project.toml default_pack")
    ap.add_argument("--tenant", default=None, help="default: config/project.toml default_tenant")
    ap.add_argument("--fixture", type=Path, default=None, help="default: <pack>/fixtures/<tenant>.json")
    args = ap.parse_args(argv)
    from agentkit.record.durable_io import load_record
    from agentkit.transport import SeatRpcClient

    registry = load_pack(args.pack or default_pack())
    tenant = args.tenant or default_tenant()
    fixture_path = args.fixture or Path(registry.extras.get("fixtures_dir", ".")) / f"{tenant}.json"
    fixture = load_record(fixture_path) if fixture_path.exists() else None
    client = SeatRpcClient.for_tenant(tenant, extra_read_only=registry.read_only)
    client.initialize()
    catalog = client.catalog()
    problems, warnings = assess(catalog, registry, fixture)
    print(f"[preflight] {tenant}: {len(catalog)} tools, fingerprint {catalog.fingerprint()}"
          f" (fixture: {(fixture or {}).get('tools_fingerprint') or 'none'})")
    for w in warnings:
        print(f"  WARNING  {w}")
    for p in problems:
        print(f"  PROBLEM  {p}")
    print("  required tools: ok" if not problems else f"  {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
