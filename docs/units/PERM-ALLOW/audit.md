# PERM-ALLOW audit

Goal: `.claude/settings.json` pre-approves every tool normal sessions use (`permissions.allow`) and keeps forbidden actions forbidden (`permissions.deny`, wins over allow). Not a bypass mode (D-070).

## Findings
- `.claude/settings.json` holds only the SessionStart hook `bash scripts/cloud/setup.sh`, timeout 1200. No unit manifest lists the file; no open PR touches it.
- Branch: the harness designated `claude/perm-allow-settings-p045qv` (created at base tip 582ebf33); it is the single PR head (#724) instead of `mod/perm-allow`.
- Test conventions: `scripts/tests/<name>.test.sh` runner + `scripts/tests/covers/<name>.json` sidecar; `units/engine-test-support/unit.json` `paths` owns the claude-session tests. `scripts/lib/gate-script-tests.json` is not edited.
- Claude Code 2.1.312 is installed (`/opt/node22/bin/claude`), so a nested headless `claude -p` proof is possible.

## Tool names (how obtained: this session's own tool list and deferred-tool list, 2026-10-28)
Built-in: Bash, Read, Edit, Write, Glob, Grep, Agent (sub-agents; legacy name Task), Skill, WebFetch, WebSearch, NotebookEdit, ToolSearch, AskUserQuestion, Monitor, SendMessage, ListAgents, ScheduleWakeup, CronCreate, CronDelete, CronList, TaskCreate/Get/List/Update/Stop (todo list; legacy TodoWrite), SendUserFile, PushNotification, ReadNotifications, Artifact, ReportFindings, EnterPlanMode/ExitPlanMode, EnterWorktree/ExitWorktree.
MCP servers: `github` (whole server) and `claude-code-remote` (create_trigger, delete_trigger, update_trigger, list_triggers, fire_trigger, get_trigger, send_later, create_session, send_message, subscribe_pr_activity, ...): the scheduled check-in create and delete tools of the GX-29 prompt.

## What a prefix deny can and cannot catch
- Catches: `scripts/ship-tail ...`, `./scripts/ship-tail ...`, `bash scripts/ship-tail ...`, `git push -f/--force/--force-with-lease`, `git push ... +refspec`, Write/Edit on `.github/workflows/**`.
- Cannot catch: `cd scripts && ./ship-tail`, `python3 scripts/lib/ship_tail.py`, `sh -c "..."` with indirection, a force push through another git alias, a workflow file created by a Bash redirect (`echo > .github/workflows/x`), the GitHub MCP file tools writing that path. These stay covered by the second layer (engine guards: push guard, structure check, production freeze D-054). This is not a complete sandbox.
