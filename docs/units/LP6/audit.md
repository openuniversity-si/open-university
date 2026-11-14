# LP6 audit: planner role session and wake path

Base `mod/roadmap-integration` at `3c834942` (LP2 #701 merged). Read-only findings with evidence.

## Cited sources (verified on the base)

| Cited | Exists | Evidence |
|---|---|---|
| `scripts/lib/planner_role.py` stub | yes | `append_decision(program, change)` raises `NotImplementedError('LP6')` |
| `scripts/lib/adapters/planner_wake*.py` | no file yet; path claimed | `units/engine-coordinator/unit.json` paths |
| `scripts/tests/test_planner_role.py` | no file yet; path claimed | same manifest |
| `scripts/lib/engine_role.py` role API | yes | `LockedRole` (`run`, `renew`, `pending`, `drain`), `RoleHalt`, `default_owner(producer)`; the lock is `forge_events.ForgeEvents.lock/unlock` (`forge_events.py:300-309`) |
| `plan_live.append` / `read_log` / `digest` | stubs (LP3 in parallel) | `plan_live.py:28-47`; `origin/mod/lp3` at `aa6b0fab` still stubs |
| `contracts/events/plan.candidate.v1.json` | yes | 14 required fields, `disposition` in {candidate, seen} |
| `config/registry/planner.json` | yes, 8 keys | `planner.log_branch`, `planner.enabled`, `planner.decision_context_max_tokens`, `planner.subagents_max` name `planner_role.py` as a reader |
| `docs/process/live-planning.md` §5 "Role" | stub line | line 83-85 |
| Premises P-48 (plan log on `plan/live`), P-50 (planner woken by events) | yes | `docs/process/premises/plan-log-on-plan-live-branch.yml`, `planner-session-woken-by-events.yml` |
| Launcher port pattern for the wake port | yes | `adapters/launcher.py` (port, `DryRunLauncher`, `ADAPTERS`), `adapters/launcher_claude.py` (argv from the registry, injected runner) |

## Gaps

1. **Registry keys the role needs do not exist in `planner.json`**: the role lock ref, its lease, the producer/owner
   name, the bound on non-fast-forward retries, the git remote, the wake adapter choice, its argv, timeout, session env
   name, dry-run output directory and a chars-per-token estimate for the context budget. `planner.json` is closed to
   edits (brief seam) → one new per-unit file `config/registry/planner-lp6.json` (keys must start with the file's owner,
   `config.check`: `planner-lp6.*`), its generated module (`scripts generate python-types`) and ONE manifest line.
2. **No lock in the in-memory forge adapters** (`MemoryAdapter`, `FileAdapter` have no `lock`); `test_train.py:80-90`
   adds one in its fake. The concurrency test needs a fake with a thread-safe lock; that stays in the test file.
3. **LP3's `append` is a stub**: the role codes against the documented signatures (`read_log(program, root)`,
   `digest(change)`, `append(program, change, root)`; "the caller commits and pushes it") through an injectable log
   module; the test passes a local stand-in with the same signatures.
4. **"Existing cloud-session send used by A Torre"**: A Torre wakes sessions with its harness's `send_message` (off-repo).
   In-repo, the only Claude call is `coordinator.launcher_argv` (`claude --remote` + brief). The Claude wake adapter uses
   a registry argv plus the planner session id read from an env var the launcher provides; no secret is read.
5. Running `plan.changed` emission through the forge port (design 3.2 "the event is still emitted as the trigger") is not
   in LP6's row; not done here.

## Known base defects expected at the gate

claude-session, root-identity, config `RegistryMemo` / flaky `config.test.sh`, cloud uid-65534 fs-encoding (env, named in
the brief); timing-sensitive tower-catalog tests.
