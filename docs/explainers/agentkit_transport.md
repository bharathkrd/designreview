# `agentkit/transport/` — communication with AgentSwitch

*Reading order: **1st**. Files: `wire.py`, `seat_rpc.py`, `rest_reader.py`, `journal.py`, `catalog.py`,
`safe_reads.py`. This module needs only `agentkit/config.py`. Written in ASD-STE100 (Simplified Technical
English) style, 2026-10-14.*

## Overview

All communication of the agent and the harness with the platform goes through this module.

| File | Use |
|---|---|
| `wire.py` | The only code that opens a socket. |
| `seat_rpc.py` | JSON-RPC 2.0 to `/api/mcp`. |
| `rest_reader.py` | A separate REST client for the verifiers. It sends only GET requests. |
| `journal.py` | Records each tool call of a run. |
| `catalog.py` | The tool catalogue as one value that you can compare. |
| `safe_reads.py` | Reads all pages of a list, and does not trust server filters. |

## Design decisions

### The network seam

- **A `Wire` with one method.** `send(method, url, headers, body, *, safe_to_repeat) -> WireReply` is all
  that the other code needs. Thus the tests and the offline simulator replace the network. They do not patch
  `urllib`.
- **Offline means offline (since 2026-10-12).** When `AGENTKIT_OFFLINE=1` (CI sets it), `UrllibWire.send`
  raises `OfflineViolation` before it opens a connection. This is intentionally not a `WireUnreachable`.
  A `WireUnreachable` becomes `FLAKY`, gets retries, and can end as a polite refusal that hides the error. A
  test replacement for `urlopen` is not the network, and the guard does not stop it.
- **TLS verification is on.** The certificates of the platform verify correctly. `AS_INSECURE_TLS=1` stops
  the verification, but only when you set it.
- **A live framing fault does not stop the client.** On 2026-09-28, each `/api/mcp` response declared
  `Transfer-Encoding: chunked` but sent a plain JSON body. Standard clients reject this. `read_body()` finds a
  body that is not really chunked and reads to the end of the stream. The server also sends
  `Connection: close`.
- **Error bodies get the same tolerance.** `read_error_body` reads a 4xx or 5xx body in the same way as
  `read_body`. Thus the incorrectly framed 401 of the platform stays a 401 and starts the login again. It
  does not cause an `IncompleteRead` crash.

### Failures and retries

- **Typed failures, not strings.** A tool call gives its payload, or it raises `SeatCallFailure`. The `kind`
  of the failure tells the caller what to do:

  | Kind | Meaning |
  |---|---|
  | `missing` | The record does not exist. Refuse. |
  | `bad_args` | The arguments are not correct. |
  | `bad_transition` | The platform does not permit this state change. |
  | `not_in_seat` | The seat does not have this tool. This is a structural refusal. |
  | `denied` | No permission. |
  | `token_expired` | The login token is no longer valid. |
  | `flaky` | A temporary error. A read can try again. |
  | `unclassified` | Any other error. |

  Where the platform gives `error.data.code`, that code sets the kind. JSON-RPC errors come with HTTP 200, so
  the client always examines the envelope. A `result.isError` is also a failure.
- **Retry only a request that cannot have had an effect.** Reads (`.list`, `.get` and the read-only
  endpoints of the pack) get retries on connection errors and on 502, 503 and 504. A write gets one attempt
  only, because a gateway error can come after the server did the write.
- **One shared login after a 401.** A 401 means that the server did not process the request. Thus the client
  logs in again one time and sends the request again one time. This is safe for writes too. When ten threads
  get a 401 together, the client still logs in only one time.
- **A token belongs to one tenant.** `SeatSession` starts from `AGENTSWITCH_TOKEN` only when `tenant_login`
  found the tenant without a password (the own tenant of the runner). A tenant with a password always logs
  in itself. Before this change, each tenant started from that token and got a 401 on the wrong tenant.

### The catalogue and safe reads

- **The catalogue is one value (since 2026-10-12).** `ToolCatalog` wraps the result of `tools/list`:
  - `fingerprint()`: 16 hex characters of SHA-256 over the sorted names and input schemas;
  - `required_args`;
  - `read_only_hint`: the annotation of the server, or `None` when it is not known;
  - `check_requirements({tool: args we send})`.

  `SeatRpcClient.catalog()` and `SimPlatform.catalog()` give a catalogue. Each run records
  `taskrun.tool_catalog = {fingerprint, count, problems}` against the `required_tools` of the pack.
- **Do not trust the filters, sorts or page limits of the server.** `read_all(client, tool, filters,
  safe_keys)` operates as follows:
  1. It sends only exact values without commas or operators, and only on keys that the pack declares safe.
  2. It reads each page through `invoke_tool`, so the journal has each page.
  3. It examines each filter again on the rows that it gets (`recheck`). A row without the field stays. A row
     that does not agree goes. It applies `ne:` correctly in code.
  4. `sort_rows` sorts in code.
- **A partial list says that it is partial.** When the server says that it has more rows than it gave,
  `read_all` adds `"complete": false`, `"server_total"` and `"received"`. The finding of the pack then marks
  that section as incomplete. It does not state facts from rows that it did not get.

### The journal is the evidence

- **One line for each call.** `JournaledSeatClient` writes one line to `tool_journal.jsonl` for each call.
  The line has the sequence number, tool, arguments, read or write, ok or error kind, a result summary and
  the seconds. The
  graders use it to prove that a dry run did not write. They do not trust the report of the agent. The
  journal never has the token or the headers.
- **The client validates the arguments before the call (since 2026-10-14).** The client compares the arguments with the
  input schema of the tool in the catalogue:
  - each necessary key must be present;
  - no unknown key, when the schema forbids unknown keys;
  - each simple JSON type must be correct.

  A bad call goes into the journal with `error_kind = "bad_args"` and `"sent": false`. Then the client
  raises `SeatCallFailure`. The call never goes to the platform. A client without a catalogue does not
  validate.
- **The verifiers use their own path.** `RestReader` has its own login and sends only GET requests. Thus an
  error in how the agent reads the platform cannot make its own check pass.

## What it does

1. `SeatSession` keeps the login of one tenant (from `config/tenants.toml`) and the token. It has a lock for
   a new login.
2. `SeatRpcClient.initialize()` does the MCP handshake.
3. `seat_catalog()` reads all pages of `tools/list` (with the cursor) and keeps the result. `offers(tool)`
   examines it.
4. `invoke_tool(name, args)` gives the unwrapped payload. It uses `structuredContent` first, then the JSON in
   `content[].text`, then the raw result.
5. `fetch_every_page()` reads all pages of a `.list` tool and removes duplicate ids.
6. `RestReader.get`, `list_all` and `raw` read REST. A 404 becomes `missing`.
7. `JournaledSeatClient(client, path, start_seq=1)` wraps each client that has `invoke_tool`. Since
   2026-10-13, `start_seq` lets a resumed or replayed run continue the numbers of an existing journal. The
   journal of a replay has the original calls, then the replayed calls.

## Key types

| Name | Purpose |
|---|---|
| `SeatCallFailure(kind, tool, raw, field_errors, http_status)` | Each failure. `.retryable` is true only for `flaky`. |
| `SeatSession` | The login, the token and the lock for a new login. All users of one tenant share it. |
| `SeatRpcClient` | The MCP tools of one seat. The ids are thread-safe. |
| `RestReader` | REST with GET only, for the ground truth. |
| `UrllibWire`, `WireReply`, `WireUnreachable` | The network seam. |
| `JournaledSeatClient`, `read_journal()`, `argument_problems(schema, args)` | The call log of each run, and the argument check. |
| `ToolCatalog` | The tool catalogue and its fingerprint. |
| `read_all(client, tool, filters, safe_keys)`, `sort_rows` | Safe reads of a full list. |

## How to test

- Offline: use a fake `Wire`. The hand-written template is `tests/test_seat_rpc.py`.
- Live: `SeatRpcClient.for_tenant("suryodaya")`.
