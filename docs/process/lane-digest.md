<!-- generated from docs/process/lane.md (Rules digest) -->
0. Each command: `cd /root/wt/<fxx> && <command>`, no exports; print no credential.
1. `scripts/lane worktree <Fxx> --session <session>` in ~/the-tower (.toolchain; base mod/roadmap-integration not main; not PR #3, #41).
2. Read only the row's files, by range (`rg -n`/`sed -n`); ~15k tokens a call: batch, `| tail -20`.
3. Each commit green, pushed; no rebase/force. Trailers `Plan: N`, `Co-Authored-By: <model> <noreply@anthropic.com>`, `Claude-Session: <session>`.
4. `export CLAUDE_SESSION_URL=<session>`; `scripts/pr-body --title`; `scripts/commit-check --pr-body <file>`: checklist; `Premises: P-NN|none`; D-NNN on gate change; `Fit-Review:` from pr-body.
5. Title `<Fxx>: ...`; no `pr create`: `deliver --open` opens it.
6. `scripts/test-suite --changed` once pre-deliver; iterate `scripts/run test <name>`.
7. `scripts/deliver --open --branch units/<fxx> > ../<fxx>.log 2>&1` via `run_in_background` (never `&`), await exit. Red: fix by class, rerun; base red: friction+report.
8. Never edit fila.md.
9. Edit config/registry/<area>/, not the aggregate.
10. Friction: `scripts/friction <env|base-red|conflict|hang|tooling|rule> <s> <what>` (frictions.jsonl). Report PR, merge sha, effect, friction. One unit per lane.
11. 60 calls/15 min unmerged: stop, push green, report.
