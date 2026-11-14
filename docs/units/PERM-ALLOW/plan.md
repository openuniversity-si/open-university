# PERM-ALLOW plan

Critical path: settings (5 min) -> test (10) -> proof (10) -> gate. Docs and settings share no file; the test needs the settings content, so it follows.

1. audit.md (done).
2. plan.md (this file).
3. `.claude/settings.json`: `permissions.allow` + `permissions.deny`, hook kept. Owns that file.
4. `scripts/tests/claude-settings.test.sh` + `test_claude_settings.py` + `covers/claude-settings.json`, manifest line in `units/engine-test-support/unit.json`, CODEOWNERS via `scripts/generate`.
5. Proof (nested `claude -p`, deny proof) quoted in the PR; `retro.md`.

Premises: none. Targeted test: step 4's test. Single final gate: `scripts/gate-dev --pr 724`. Base-env failures expected (not ours): claude-session, root-identity, config tests (GX-ENV).
