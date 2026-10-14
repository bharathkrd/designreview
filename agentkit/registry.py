"""
The plug-in point between agentkit (domain-free) and a pack (domain).

A pack is a Python module exposing `register(registry)`. It fills a
Registry with:
- actions      -- the ONLY operations a graph node may perform (allowlist)
- read_only    -- tool names that are reads even though they don't end in
                  .list/.get (e.g. computed endpoints)
- probes         -- ground-truth readers: probe(reader, arg) -> observation
- checks         -- verifiers (CheckDef: what to observe + a pure check)
- mutants        -- verifier self-test faults (edit a saved run's record)
- replay_faults  -- end-to-end self-test faults: replace one node's result,
                    re-run everything downstream (agentkit.harness.replay)
- anything else under `extras` (templates, claim rules, ...)

`load_pack("packs.<name>")` or `load_pack("packs.<name>:register")`
imports the module and returns a fresh Registry, so two packs (or two
tests) never share state.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, Optional, Set

# What kind of mistake a failed check points at. Adapted from a published taxonomy of agent
# failures (task-verification and specification failures), reduced to what a saved run can show:
#   wrong_fact        a fact the agent stated differs from the platform
#   fabrication       something stated that no evidence supports (invented value, record, claim)
#   ignored_evidence  evidence the agent read but left out of the answer
#   policy_breach     the agent did something it must not (a write in a dry run, an absent tool)
#   premature_stop    the run ended without finishing (crash, no answer)
#   verification_gap  a conclusion reached without the check that supports it (refused without looking)
#   inefficiency      wasted work (the same read repeated)
FAILURE_MODES = ("wrong_fact", "fabrication", "ignored_evidence", "policy_breach", "premature_stop",
                 "verification_gap", "inefficiency")


@dataclass(frozen=True)
class ActionSpec:
    name: str
    fn: Callable[..., Any]  # fn(env, args, results) -> NodeResult | value
    description: str = ""
    writes: bool = False
    retries: int = 0  # extra attempts on a FLAKY transport error (never for writes)
    # Optional agentkit.graph.policies.RetryPolicy; when set it replaces `retries`.
    retry: Optional[Any] = None
    # For a write action: preview(env, args, results) -> what it WOULD send.
    # In a dry run the engine calls this instead of fn and ends the node
    # HANDED_OFF with {"would_file": preview, "filed": False}; with no preview
    # a dry-run write is simply DECLINED. A preview must not write.
    preview: Optional[Callable[..., Any]] = None
    # Seconds one attempt may take; past it the node ends FAILED ("timeout"). None = no limit.
    timeout_s: Optional[float] = None


@dataclass(frozen=True)
class CheckDef:
    """A verifier: `observes(params) -> [probe keys]` it needs captured before
    and after the run, and `check(bundle, params) -> [CheckOutcome]`, a pure
    function over the saved run folder."""
    name: str
    check: Callable[..., Any]
    observes: Callable[[Dict[str, Any]], Any] = lambda params: []
    failure_mode: str = ""  # one of FAILURE_MODES; reported per failed check, never scored


@dataclass(frozen=True)
class MutantDef:
    """A verifier self-test fault: `apply(bundle) -> bundle | None` breaks one
    thing in a copy of a passing run; the check named `target` must then fail.
    Returning None means "not applicable to this run"."""
    name: str
    target: str
    apply: Callable[..., Any]


@dataclass(frozen=True)
class ReplayFaultDef:
    """An end-to-end self-test fault: `apply(node_result) -> NodeResult | None`
    replaces what node `node` returned; the graph re-runs from there, the
    finding and answer are rebuilt, and the check named `target` must then
    fail. Returning None means "not applicable to this run"."""
    name: str
    node: str
    target: str
    apply: Callable[..., Any]


@dataclass
class Registry:
    name: str = ""
    actions: Dict[str, ActionSpec] = field(default_factory=dict)
    read_only: Set[str] = field(default_factory=set)
    probes: Dict[str, Callable[..., Any]] = field(default_factory=dict)
    checks: Dict[str, Callable[..., Any]] = field(default_factory=dict)
    mutants: Dict[str, Callable[..., Any]] = field(default_factory=dict)
    replay_faults: Dict[str, ReplayFaultDef] = field(default_factory=dict)
    extras: Dict[str, Any] = field(default_factory=dict)

    # ---- decorators -----------------------------------------------------

    def action(self, name: str, *, description: str = "", writes: bool = False, retries: int = 0,
               retry: Optional[Any] = None, preview: Optional[Callable[..., Any]] = None,
               timeout_s: Optional[float] = None) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
            if name in self.actions:
                raise ValueError(f"action {name!r} registered twice")
            if preview is not None and not writes:
                raise ValueError(f"action {name!r}: preview is only for write actions")
            self.actions[name] = ActionSpec(name, fn, description or (fn.__doc__ or "").strip().split("\n")[0],
                                            writes=writes, retries=0 if writes else retries,
                                            retry=None if writes else retry, preview=preview,
                                            timeout_s=timeout_s)
            return fn
        return deco

    def probe(self, name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        return self._into(self.probes, name)

    def check(self, name: str, observes: Optional[Callable[[Dict[str, Any]], Any]] = None,
              failure_mode: str = "") -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        if failure_mode and failure_mode not in FAILURE_MODES:
            raise ValueError(f"check {name!r}: unknown failure_mode {failure_mode!r}; one of {FAILURE_MODES}")

        def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
            if name in self.checks:
                raise ValueError(f"{name!r} registered twice")
            self.checks[name] = CheckDef(name, fn, observes or (lambda params: []), failure_mode)
            return fn
        return deco

    def mutant(self, name: str, target: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
            if name in self.mutants:
                raise ValueError(f"{name!r} registered twice")
            self.mutants[name] = MutantDef(name, target, fn)
            return fn
        return deco

    def replay_fault(self, name: str, node: str, target: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
            if name in self.replay_faults:
                raise ValueError(f"{name!r} registered twice")
            self.replay_faults[name] = ReplayFaultDef(name, node, target, fn)
            return fn
        return deco

    @staticmethod
    def _into(table: Dict[str, Any], name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
            if name in table:
                raise ValueError(f"{name!r} registered twice")
            table[name] = fn
            return fn
        return deco

    def declare_read_only(self, tools: Iterable[str]) -> None:
        self.read_only.update(tools)

    def get_action(self, name: str) -> ActionSpec:
        try:
            return self.actions[name]
        except KeyError:
            raise KeyError(f"{name!r} is not a registered action") from None


def load_pack(ref: str, registry: Optional[Registry] = None) -> Registry:
    module_name, _, func_name = ref.partition(":")
    module = importlib.import_module(module_name)
    register = getattr(module, func_name or "register")
    reg = registry or Registry(name=module_name)
    register(reg)
    return reg
