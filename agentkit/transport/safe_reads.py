"""
Reads that don't trust the platform's filters, sorts or page sizes.

What a pack can rely on:
- `split_filters(filters, safe_keys)` -> (server, local): only an exact, scalar,
  comma-free, operator-free value on a key the pack declares safe is sent to
  the server; everything else is applied here. A comma becomes an OR list on
  the server, and `ne:` silently drops rows whose value is NULL.
- `where(rows, **equals)` -- exact equality in code; `None` means "empty".
- `recheck(rows, **filters)` -- like `where`, but a row that doesn't carry a
  field at all is kept (nothing proves it wrong); a row whose value differs
  is dropped. A value "ne:<x>" means not-equal done right (empty values
  kept); any other operator prefix is a ValueError, never a silent literal
  match. This is what `read_all` applies to what the server returned.
- `not_equal(rows, field, value)` -- a correct "not equal": rows with an empty
  value are KEPT (the platform's `ne:` loses them).
- `sort_rows(rows, key, descending=False)` -- sort in code (the server's
  sort_order isn't validated); empty values last, stable.
- `exact_name(rows, field, name)` -- exact match first, then case-insensitive
  exact; never a substring.
- `read_all(client, tool, filters, safe_keys)` -- page a `.list` tool through
  `client.invoke_tool` (so every page is journaled) with `split_filters`, then
  re-check every filter in code. Returns {"data": rows, "total": len(rows)},
  the shape a single `.list` page has, plus "complete": False and
  "server_total" when the server said there were more rows than it returned
  (a short page before the total was reached -- a partial payload).

Provenance: the defensive-read idea (send only exact filters, page in full,
re-check filters and do "not equal" in code) is referred from an outside
source and rebuilt here, generalised to take the safe keys from the caller
and journaled through invoke_tool.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

UNSAFE_PREFIXES = ("ne:", "gt:", "lt:", "gte:", "lte:", "like:", "in:", "not:")
DEFAULT_PAGE = 100
DEFAULT_MAX_PAGES = 40


def _server_safe(value: Any) -> bool:
    if value is None or isinstance(value, (list, tuple, set, dict)):
        return False
    text = str(value)
    return "," not in text and not text.lower().startswith(UNSAFE_PREFIXES)


def split_filters(filters: Mapping[str, Any], safe_keys: Iterable[str]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    safe = set(safe_keys)
    server = {k: v for k, v in filters.items() if k in safe and _server_safe(v)}
    local = {k: v for k, v in filters.items() if k not in server}
    return server, local


def _same(actual: Any, wanted: Any) -> bool:
    if wanted is None:
        return actual in (None, "")
    if isinstance(wanted, bool):
        return bool(actual) == wanted
    return str(actual) == str(wanted)


def where(rows: Iterable[Dict[str, Any]], **equals: Any) -> List[Dict[str, Any]]:
    return [r for r in rows if all(_same(r.get(k), v) for k, v in equals.items())]


def _passes(row: Dict[str, Any], key: str, wanted: Any) -> bool:
    if key not in row:
        return True
    if isinstance(wanted, str) and wanted.lower().startswith(UNSAFE_PREFIXES):
        op, _, operand = wanted.partition(":")
        if op.lower() != "ne":
            raise ValueError(f"filter {key}={wanted!r}: only exact values and ne: are supported in code")
        return not _same(row.get(key), operand)
    return _same(row.get(key), wanted)


def recheck(rows: Iterable[Dict[str, Any]], **filters: Any) -> List[Dict[str, Any]]:
    return [r for r in rows if all(_passes(r, k, v) for k, v in filters.items())]


def not_equal(rows: Iterable[Dict[str, Any]], field: str, value: Any) -> List[Dict[str, Any]]:
    return [r for r in rows if not _same(r.get(field), value)]


def sort_rows(rows: Iterable[Dict[str, Any]], key: str, descending: bool = False) -> List[Dict[str, Any]]:
    rows = list(rows)
    present = [r for r in rows if r.get(key) not in (None, "")]
    empty = [r for r in rows if r.get(key) in (None, "")]
    return sorted(present, key=lambda r: r[key], reverse=descending) + empty


def exact_name(rows: Iterable[Dict[str, Any]], field: str, name: str) -> List[Dict[str, Any]]:
    rows = list(rows)
    exact = [r for r in rows if r.get(field) == name]
    wanted = name.casefold()
    return exact or [r for r in rows if isinstance(r.get(field), str) and r[field].casefold() == wanted]


def read_all(client: Any, tool: str, filters: Optional[Mapping[str, Any]] = None, *,
             safe_keys: Iterable[str] = (), page: int = DEFAULT_PAGE,
             max_pages: int = DEFAULT_MAX_PAGES) -> Dict[str, Any]:
    filters = dict(filters or {})
    server, _ = split_filters(filters, safe_keys)
    rows: List[Dict[str, Any]] = []
    offset, server_total = 0, None
    for _ in range(max_pages):
        payload = client.invoke_tool(tool, {**server, "limit": page, "offset": offset})
        batch = payload.get("data") if isinstance(payload, dict) else payload
        if not isinstance(batch, list):
            break
        rows.extend(r for r in batch if isinstance(r, dict))
        offset += len(batch)
        total = payload.get("total") if isinstance(payload, dict) else None
        if isinstance(total, (int, float)) or (isinstance(total, str) and total.isdigit()):
            server_total = int(total)
        if not batch or len(batch) < page or (server_total is not None and offset >= server_total):
            break
    out: Dict[str, Any] = {}
    if server_total is not None and offset < server_total:
        out = {"complete": False, "server_total": server_total, "received": offset}
    rows = recheck(rows, **filters)  # every filter re-checked here, server-side ones included
    return {"data": rows, "total": len(rows), **out}
