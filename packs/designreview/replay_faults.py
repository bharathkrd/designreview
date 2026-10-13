"""
Design-review end-to-end self-test faults (agentkit/harness/replay.py).

A mutant (mutants.py) edits a finished run's record, so it tests the checks
alone. A replay fault goes one level deeper: it replaces what ONE node
returned, the graph re-runs everything downstream of it offline, the finding
and the answer are rebuilt from scratch, and the named check must then fail.
That proves the whole path -- node -> finding -> answer -> check -- turns a
wrong platform answer into a failed grade, not just the last step.
A fault returns None when it doesn't apply to that run.
"""

from __future__ import annotations

import copy
import re
from typing import Optional

from agentkit.graph.node_result import FAILED, RESOLVED, NodeResult
from agentkit.registry import Registry
from agentkit.transport.seat_rpc import FLAKY

_MM = re.compile(r"(\d+(?:\.\d+)?)(\s*mm)")


def register_replay_faults(reg: Registry) -> None:
    @reg.replay_fault("gate_reports_ready", node="release_gate", target="release_gate_matches_db")
    def gate_reports_ready(r: NodeResult) -> Optional[NodeResult]:
        """The release gate answers "ready, nothing open" although the platform says not ready."""
        if r.verdict != RESOLVED or not isinstance(r.data, dict):
            return None
        data = copy.deepcopy(r.data)
        gate = data.get("result", data)
        if not isinstance(gate, dict) or gate.get("ready") is not False:
            return None
        gate.update(ready=True, reason_codes=[], reasons=[], blockers=[])
        return NodeResult(RESOLVED, data=data)

    @reg.replay_fault("latest_note_altered", node="revisions", target="revision_delta_matches_db")
    def latest_note_altered(r: NodeResult) -> Optional[NodeResult]:
        """The newest version's commit message states a different quantity (+1.1 mm)."""
        if r.verdict != RESOLVED or not isinstance(r.data, dict):
            return None
        data = copy.deepcopy(r.data)
        rows = [x for x in data.get("data") or [] if isinstance(x, dict)]
        if not rows:
            return None
        latest = max(rows, key=lambda x: x.get("version_number") or 0)
        note = latest.get("commit_message") or ""
        if not _MM.search(note):
            return None
        latest["commit_message"] = _MM.sub(lambda m: f"{float(m.group(1)) + 1.1:.1f}{m.group(2)}", note, count=1)
        return NodeResult(RESOLVED, data=data)

    @reg.replay_fault("milestones_unreadable", node="milestones", target="schedule_matches_db")
    def milestones_unreadable(r: NodeResult) -> Optional[NodeResult]:
        """The milestone read fails after its retries."""
        if r.verdict != RESOLVED:
            return None
        return NodeResult(FAILED, reason="replay fault: milestone list unreadable", error_kind=FLAKY)
