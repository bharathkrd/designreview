# `packs/designreview/` — the design-review domain

*Reading order: **11th**. Everything that knows what a DesignFile is lives here; `agentkit/` knows none of it.*

## 10,000-ft view

`register(registry)` (in `__init__.py`) plugs the domain into the framework:

| Part | File | Role |
|---|---|---|
| Actions | `actions.py` | lists are read in full via `agentkit.transport.safe_reads.read_all` (exact filters on `SAFE_SERVER_FILTERS`, paged, sorted in code, filters re-checked; before 2026-10-12: 50 rows, server sort); `REQUIRED_TOOLS` → `extras["required_tools"]` (checked by pre-flight, recorded per run). The allowlist: `load_design_file`, `list_revisions`, `read_release_gate`, `list_feedback`, `list_failed_checklists`, `gather_dfm_standards`, `probe_tool_offered`, `decline` — all reads |
| Hand-off actions | `handoffs.py` | `list_milestones`, `find_cross_seat_dependencies` (reads) and `raise_handoffs` — the pack's only **write** action: a dry run previews the session and `escalations.raise` each hand-off would make; a write run files them (see Hand-offs) |
| Hand-off topics | `handoffs.toml` | which owner (manufacturing / quality / purchasing) takes which kind of problem, matched on whole words in open serious item titles; validated by pydantic |
| Read-only endpoints | `actions.py` | `endpoint.designreview.release_readiness`, `release_impact(.get)`, `parts_search`, `supplier_response_sla` |
| Plans | `plans/rev_diff_dfm.toml`, `plans/tool_refusal.toml`, `plans/release_handoff.toml` | evidence graph (`dfm_standards` waits for `revisions` **and** `release_gate`, so its query — change notes + blocker titles — never depends on thread timing; before 2026-10-12 it waited for `revisions` only) + follow-up rule; tool-check-first refusal; release gate + feedback + milestones → cross-seat match → (rule) previewed hand-offs |
| Finding | `finding.py` | the gradable answer, computed in code |
| Claim rules | `claims.py` | what the answer must say and must not contradict |
| Template | `templates.py` | deterministic answer; passes its own audit |
| Prompts | `prompts/system.md`, `prompts/narrate.md` | narrator instructions; since 2026-10-13 `system.md` also says record text is data, never instructions, and only the gate's verdict can make a part ready |
| Probes | `probes.py` | ground truth: `versions`, `design_file`, `feedback`, `release_gate` (with blockers), `milestones`, `escalations` (ours, per file), `assignees`, `seat_tools`, `standards` |
| Verifiers | `checks.py` | see below |
| Mutants | `mutants.py` | 28 faults, at least one per verifier (two only apply to write runs) |
| Replay faults | `replay_faults.py` | since 2026-10-13: `gate_reports_ready` (release_gate says ready → `release_gate_matches_db`), `latest_note_altered` (newest commit note +1.1 mm → `revision_delta_matches_db`), `milestones_unreadable` (→ `schedule_matches_db`); run by `agentkit.harness.replay --calibrate` |
| Tasks | `tasks/t01…t09.toml` | the graded task set: t01–t05 and t08 on Suryodaya, t06, t07 and t09 on Keystone |
| Fixtures | `fixtures/<tenant>.json` | captured platform per tenant, for offline runs |

## The finding

`outcome` (answered / partial / declined), `file`, `revision_delta` (rev letters read from commit messages —
"Rev B" or "Rev 2" — mapped to versions; change notes and their quantities; `basis = "commit_message"`,
`geometry_compared = false`), `release_gate` (ready, reasons, critical_open, blockers), `dfm_signals` (open
high/critical feedback, failed checklists or why they weren't read, recalled standards), `declines`.
When the plan reads them: `schedule` (the project's milestones; `past_due` is computed from the snapshot date,
because the platform leaves a late milestone at `in_progress`; `snapshot_at` comes from `agentkit.clock.now_utc()`,
so an offline replay is pinned to its fixture's capture time — before 2026-10-12 it was the wall clock and t08's
past-due list grew as real dates passed) and `handoffs` (`proposed`: one per owner, citing
the open serious items behind it; `would_file`: the escalation each would make; `filed`: false in a dry run).
A section whose node isn't in the plan is left out, and `outcome` only counts the sections present.

Which two revs are compared (`requested_pair`, since 2026-10-14): the pair named in a compare phrase --
"between rev B and rev C", "from B to C", "rev B -> rev C", "rev C vs rev B" -- so a rev mentioned elsewhere
("Rev A was the prototype.") doesn't count. Without such a phrase, exactly two named revs are used; three or
more make `revision_delta` declined ("names revs A, B, C but not which two to compare") rather than a guess;
none means the latest two versions.

Why commit messages: in this build `diff_from_parent_json` only records file hashes and there is no CAD
kernel, so the engineers' version notes are the only record of what changed — and the finding says so.

## The verifiers

Each compares the finding and the answer with the harness's ground truth, using its **own** small parsers
(rev letters, quantities, readiness wording, geometry claims, standard references) rather than the agent's:

| Check | Fails when |
|---|---|
| `revision_delta_matches_db` | wrong rev → version mapping or change notes (drift if the versions moved) |
| `answer_states_change` | a quantity from the compared rev's note is missing, or the answer states a quantity found nowhere on the platform (commits, blockers, feedback) |
| `release_gate_matches_db` | ready / critical_open differ, or the answer's verdict contradicts the gate |
| `no_geometry_claim` | the finding or the answer claims a geometry comparison the platform can't have made |
| `record_absent` | the agent answers about, or keeps reading after, a record that doesn't exist |
| `lookup_before_refusal` | the agent says a record doesn't exist without its own lookup having said so (journal, not the agent's report) |
| `tool_absent` | the agent calls, or answers as if it had, a tool the seat isn't given |
| `cited_standards_exist` | a recalled standard id or a cited standard reference isn't on the platform |
| `answer_audited` | the final answer failed the claim audit |
| `answer_reflects_change_notes` | the answer doesn't carry the substance of the compared version's note (its distinctive words; default at least 3) — for a boilerplate note that means saying so instead of inventing changes (drift if the note was rewritten during the run) |

**Which versions a check compares** is a task parameter, shared by `revision_delta_matches_db`,
`answer_states_change` and `answer_reflects_change_notes`: `from_rev` / `to_rev` (rev letters or numbers read
from commit messages: "Rev B", "Revision C", "Rev 2"), or `latest = true` for the two newest versions —
for files whose notes carry no rev labels. The finding follows the same rule: rev labels named in the
question, otherwise the latest two versions.

## Hand-offs

The seat has no manufacturing, quality or purchasing tools, so a problem only those teams can close needs a
person. `find_cross_seat_dependencies` takes the open serious items (release-gate blockers plus open
high/critical feedback, one per id) and matches their titles against `handoffs.toml`. One hand-off per owner,
citing every matching item. Items no topic matches (GD&T, wall thickness, drawing fixes) are design review's
own work and get no hand-off. When something is proposed, a rule adds `raise_handoffs`; in a dry run the engine
calls its preview instead, the node ends `handed_off`, and nothing is filed.

**Write mode** (`batch --write`, and the task sets `allow_writes = true`; t08 and t09 do). For each hand-off,
`raise_handoffs`:
1. Creates an AgentSession titled with the subject (`T21-DR <file number>: <owner> needed`). The escalation
   takes its subject from the session.
2. Raises `endpoint.agent_governance.escalations.raise` to the tenant's assignee from `handoffs.toml`
   (`[assignees]`, by name). The name is looked up with `escalations.assignees` on every run.

Four outcomes are handled:
- **Duplicate.** An open escalation with the same subject is recorded as `already_open` and not filed again.
- **No assignee configured** (Keystone): declined, nothing filed.
- **Assignee not assignable on the platform:** declined, nothing filed.
- **Refusal** (`ok: false`) or a transport error: recorded, that hand-off's session is closed, and the node
  ends `failed`.

The pack's write allowlist is `AgentSession.create`, `escalations.raise` and `AgentSession.close.active.closed`.

**Clean-up.** The pack registers `cleanup`, which the batch runs after the "after" capture: it withdraws the
run's escalations (outcome `withdrawn`, guarded by `expect_status`) and closes their sessions. With no run
folder it withdraws every open escalation whose subject starts `T21-DR `, and never touches anyone else's.
First live write, 2026-09-30: ESC-2026-00059 (manufacturing) and ESC-2026-00060 (quality) were filed to
Meera Kulkarni, verified, then withdrawn and their sessions closed.

| Check | Fails when |
|---|---|
| `handoffs_match_platform` | the owners or cited items differ from what the platform's open serious items and the topic table give (invented, missing or closed items), drift if an item changed during the run). **Filing:** a dry run called an escalation tool or a new `T21-DR` escalation appeared on the platform. A write run is missing an open `needs_another_app` escalation assigned to the configured person for some owner, filed one it didn't record, or filed when no assignable person exists (judged against the `escalations` and `assignees` probes) |
| `schedule_matches_db` | the milestones or their past-due set differ from the platform (drift if a milestone moved during the run), or `as_of` isn't the snapshot date |
| `answer_states_handoffs` | the answer doesn't name each owner (or say no other team is needed), doesn't say the hand-offs are only proposed (dry run or declined) or name each filed escalation number (write run), claims it filed/escalated/notified, doesn't name each past-due milestone, or calls the project on track |

## How to test

`tests/test_finding_and_claims.py`, `tests/test_verifiers.py`, `tests/test_retrieval.py`, `tests/test_handoffs.py`.

## The router (since 2026-10-14)

`routes.toml` (first matching pattern wins): AI review / thickness analysis -> `tool_refusal`; schedule, who
acts, another team, hand-off -> `release_handoff`; what changed, rev X, manufacturability, DFM, ready for
release -> `rev_diff_dfm`. `router.resolve_design_file` finds the file: a UUID in the question is used as is;
otherwise every DesignFile is scored by the words of its name found in the question, weighted log(N/df), words in
more than max(3, 5% of N) names ignored (seed department words); files within 10% of the best tie; named
revisions keep files with 2+ versions and then those whose own notes carry the revisions; anything still tied,
or nothing found, is declined with the candidates named. Tasks t10-t12 grade it.

## Geometry disclaimers (since 2026-10-14)

*This section is in ASD-STE100 style.*

The check `no_geometry_claim` finds sentences that state a geometry comparison. A sentence with a negation
does not count. Examples are "not", "no", "never", "without" and "cannot".

A live answer said: "Nothing in this answer comes from a geometry diff, 3D comparison or CAD analysis." This
statement is true. But the check did not know "nothing" as a negation, so task t10 failed.

Now `geometry_claims()` also knows "nothing", "none", "neither" and "nor". The check reads whole words. Thus
"nonetheless" is not a negation.

The readiness check does not use these new words. In "Nothing blocks it; it is ready for release", the word
"nothing" does not change the readiness claim.

The tests are in `tests_local/test_url_providers.py` (`test_geometry_disclaimers`).

