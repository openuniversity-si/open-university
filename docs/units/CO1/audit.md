# CO1 audit (read-only; cheap evidence only, no suites run)

Brief: one event-driven coordinator with programs as first-class objects (D-069). Base `mod/roadmap-integration` @ 79045314.

## Findings
| Area | Evidence | Consequence for CO1 |
|---|---|---|
| Event port | `scripts/lib/forge_events.py`: `ForgeEvents.read/emit`, `MemoryAdapter`, `replay`, `new_pr_state`; catalog in `contracts/events/*.v1.json` (`work.assigned`, `pr.opened`, `pr.ready`, `pr.merged`, `session.ended/failed`, `gate.*`, `defect.routed`, `train.*`) | State is a pure fold over envelopes; no new state store. Launch is a `work.assigned` emit (existing contract), so no new event type is needed. |
| Config registry | `config/registry/<owner>.json` (x-owner, per-key default, `x-unit`, `x-readers`), generated `scripts/lib/generated/config_registry_<owner>.py`, `config.get` | Every limit (sessions per account, launch rate, retry budget, quota headroom) is a `coordinator.*` key. A new registry file needs `scripts/generate` output. |
| Known defects (KD1) | `defect_router.route(root, port, repo, base_sha, queue, by)` emits `work.assigned` + `defect.routed`; `defects.load` | Coordinator calls it through an injected `router` callable; never edits it. Action `open_fix_unit` carries the defect id. |
| Merge train (TR1) | `train.queue_entry(events, head)` (a `pr.ready` resting on a passed `gate.passed` of the same head, not out of queue), `train.enabled` flag | Action `enqueue` is advisory: the PR becomes queue-eligible by the same predicate; the coordinator only reads it via `train.queue_entry`. |
| Selective gate (GS1) / status comment (GV1) | `gate_select.py`, `gate_status.py` | Used through their CLIs only. Nothing to import. |
| Lessons (LR1) | No lessons module, folder or registry on the base (`rg -il lesson scripts docs` hits only prose). LR1 is not merged yet | `lessons` is a port (`for_area(area)`, `aggregate(unit_ids)`) with a file adapter reading a registered glob and a null adapter. The retro aggregator degrades to unit `retro.md` headings. When LR1 lands, its adapter replaces the file one. |
| Agent port | `adapters/agent.py` runs one non-interactive turn (`--print`). It does not start a cloud session | A separate launcher port (`launch(brief) -> session id`), adapter for the Claude Code cloud CLI. `providers.*` and `engine-vendors.json` need an entry for the new CLI. |
| Unit manifests | `units/<id>/unit.json`, `contracts/units/unit.v1.json`; CODEOWNERS is generated | New unit `engine-coordinator` owning the new paths; `scripts/generate codeowners`. |
| Script tests | `scripts/lib/gate-script-tests.json` maps tests to covers; `scripts/tests/<name>.test.sh` wraps `test_<name>.py` | One mapping entry plus `coordinator.test.sh`. |
| Migration source | `v3/queue.json` does not exist in the repository or on this machine | Seed from the unit list in the brief; ship a reader (`migrate-queue`) accepting the queue file when an operator has it. Decision recorded in the PR. |
| Padrão texts | The "save often" and "decide then report" texts live only in launch prompts (the brief), nowhere in git | Move them verbatim into `docs/padrao/` (versioned `v1`), loaded by the brief renderer. |

## Duplicates checked
`rg -n "coordinator|program" scripts/lib config/registry`: nothing relevant (`scripts/units/*` is unit manifests, `scripts/train` is the merge train). `scripts/idea_to_prod.py` is a single-change flow and is left alone.

## Known base defects expected
`scripts/tests/generate.test.sh` (`intents-doc.ts`) and `scripts/tests/premises.test.sh` (`measurement:S1`), as in GV1's plan; owners per `docs/operations/known-defects.md`.
