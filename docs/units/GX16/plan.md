# GX-16 plan

Critical path (~60 min): 3 -> 4 -> 5 -> 6 -> gate. Edges 3->4 are real (the measured count is the baseline); 4/5 share gate_status.py (file collision, run in sequence); 6 touches forge_github.py only and can run in parallel with 5 (done by one writer here).

Premises: P-45 (GA-P03, our own status; low). No CRITICAL premise.

1. [x] audit.md (what #718/#720/GX-17 already did).
2. [ ] plan.md.
3. [ ] Counter: `github_api` records `W|R METHOD /endpoint` (ids and shas normalised) in the per-run count file; `scripts/lib/github_api.py`. Test in github-cli. PR body gets the real count of one gate before the change.
4. [ ] Status shape: one comment per PR (`gate.status_one_per_pr`, true), edited across heads, superseded head collapsed; PATCH at stage end only, `status_min_interval_s` 60; second `begin` is a replan (no forced edit, no second status). `gate_status.py`, `gate.json`, `test_gate_status.py`.
5. [ ] Red rows carry the D-027 class and the log path; signatures through `redact()`. `gate_status.py`, test.
6. [ ] Body above the limit is split into continuation comments, never fails the gate; `forge_github.py`. Test.
7. [ ] Retro, numbers.

Config: `secondary_limit_retries/backoff_s` are already `github-client.limit_retries` and `secondary_wait_min_s` (#720); no duplicate keys added. New: `gate.status_one_per_pr`. Rollback: `gate.status_one_per_pr=false` restores per-head comments; `gate.status_min_interval_s` back to 15.
Expected base defects: KD-335a14a4, KD-71c8e5fe, KD-27b768cb, KD-a3870679, KD-41f822d3; env tests claude-session, root-identity, config.
