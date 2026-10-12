"""
One "now" for the framework and its packs.

Anything whose result depends on the date (a finding's snapshot time, which
milestones are past due) reads the time through `now_utc()`, so a run can be
pinned to a fixed instant:

- `AGENTKIT_FROZEN_NOW=<ISO-8601 with timezone>` freezes it for the process
  (a manual override, e.g. to reproduce a run from a given day);
- `frozen_now(iso)` freezes it for a block (the offline batch freezes each
  task to its fixture's capture time, so a replay gives the same answer on
  any day);
- otherwise it is the live UTC clock.

The environment variable wins over `frozen_now`. A frozen value without a
timezone, or one that isn't a date, is a ValueError: a silently wrong clock
would change graded answers.
"""

from __future__ import annotations

import datetime as dt
import os
import threading
from contextlib import contextmanager
from typing import Iterator, List

FROZEN_ENV = "AGENTKIT_FROZEN_NOW"

_lock = threading.Lock()
_frozen: List[dt.datetime] = []  # stack of frozen_now() values; process-wide so worker threads see it


def parse_instant(value: str) -> dt.datetime:
    """ISO-8601 with a timezone -> aware UTC datetime."""
    try:
        parsed = dt.datetime.fromisoformat(value.strip())
    except (ValueError, AttributeError) as e:
        raise ValueError(f"not an ISO-8601 instant: {value!r}") from e
    if parsed.tzinfo is None:
        raise ValueError(f"frozen time needs a timezone (e.g. +00:00): {value!r}")
    return parsed.astimezone(dt.timezone.utc)


def now_utc() -> dt.datetime:
    env = os.getenv(FROZEN_ENV)
    if env:
        return parse_instant(env)
    with _lock:
        if _frozen:
            return _frozen[-1]
    return dt.datetime.now(dt.timezone.utc)


@contextmanager
def frozen_now(value: str) -> Iterator[dt.datetime]:
    instant = parse_instant(value)
    with _lock:
        _frozen.append(instant)
    try:
        yield instant
    finally:
        with _lock:
            _frozen.remove(instant)
