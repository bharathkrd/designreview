"""
RetryPolicy: when and how long to wait before a node's action is tried again.

    RetryPolicy(max_attempts=3, initial_interval=0.5, backoff_factor=2.0,
                max_interval=128.0, jitter=False, retry_on=<FLAKY transport errors>)

- `max_attempts` counts every attempt, the first one included (1 = never retry).
- The wait before attempt n+1 is min(max_interval, initial_interval * backoff_factor**(n-1)),
  plus a uniform 0-1 s when `jitter` is on (spreads retries from parallel nodes).
- `retry_on` is a tuple of exception types or a predicate `fn(exc) -> bool`. The default
  retries only a transport failure of kind FLAKY (timeout, 5xx, dropped connection);
  "not found" / "not in seat" / "denied" are answers, not glitches.
- A write action is never retried, whatever its policy says (the engine enforces it):
  a timed-out write may have landed.

Jitter is off by default so offline replays and CI wait the same every time; the random
source is injectable for tests. `ActionSpec.retries = n` (the older integer form) still
works and means RetryPolicy.from_retries(n, backoff_s): n extra attempts, waits of
backoff_s, 2*backoff_s, 4*backoff_s ... with no cap -- exactly what the engine did before.

The interval formula and the "attempts include the first call, re-raise the last error"
rules are adapted from an external open-source agent-graph design (referred to from
outside sources); the FLAKY-only default is ours.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Callable, Optional, Tuple, Type, Union

from agentkit.transport.seat_rpc import FLAKY, SeatCallFailure

RetryOn = Union[Type[BaseException], Tuple[Type[BaseException], ...], Callable[[BaseException], bool]]


def retry_flaky_transport(exc: BaseException) -> bool:
    """The default: retry a transport failure the platform may not repeat."""
    return isinstance(exc, SeatCallFailure) and exc.kind == FLAKY


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    initial_interval: float = 0.5
    backoff_factor: float = 2.0
    max_interval: float = 128.0
    jitter: bool = False
    retry_on: RetryOn = retry_flaky_transport

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts counts the first attempt too; it must be >= 1")
        if self.initial_interval < 0 or self.max_interval < 0 or self.backoff_factor < 1:
            raise ValueError("intervals must be >= 0 and backoff_factor >= 1")

    @classmethod
    def from_retries(cls, retries: int, backoff_s: float = 1.0) -> "RetryPolicy":
        """The integer form (`ActionSpec.retries`): n extra attempts, doubling waits, no cap."""
        return cls(max_attempts=max(0, int(retries)) + 1, initial_interval=max(0.0, backoff_s),
                   backoff_factor=2.0, max_interval=float("inf"), jitter=False)

    def should_retry(self, exc: BaseException, attempts_made: int) -> bool:
        if attempts_made >= self.max_attempts:
            return False
        on = self.retry_on
        if isinstance(on, type) or (isinstance(on, tuple) and all(isinstance(t, type) for t in on)):
            return isinstance(exc, on)
        return bool(on(exc))

    def interval(self, attempts_made: int, rng: Optional[Callable[[], float]] = None) -> float:
        """Seconds to wait after `attempts_made` failed attempts (>= 1) before the next."""
        wait = min(self.max_interval, self.initial_interval * self.backoff_factor ** max(0, attempts_made - 1))
        if self.jitter:
            wait += (rng or random.random)()
        return wait


def policy_for(action: Any, default_backoff_s: float = 1.0) -> RetryPolicy:
    """The policy an action runs under: its own `retry`, else its integer
    `retries`; a write action always gets a single attempt."""
    if getattr(action, "writes", False):
        return RetryPolicy(max_attempts=1)
    own = getattr(action, "retry", None)
    if own is not None:
        return own
    return RetryPolicy.from_retries(getattr(action, "retries", 0) or 0, default_backoff_s)
