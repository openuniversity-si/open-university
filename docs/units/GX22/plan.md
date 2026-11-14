# GX-22 plan

One merge rule in `config/registry/merge.json` (owner `merge`, unit engine-delivery); P-G3 switch default = today's rule.

## Commits (dependency graph)
- [ ] 1. audit.md (done)
- [ ] 2. plan.md (this file)
- [ ] 3. Registry + harvested rule: `config/registry/merge.json` (`merge.max_behind_base` 20, `merge.require_exact_head` true,
  `merge.require_mergeable` true, `merge.tier1_requires_base_merge` true; BD1's `merge.regate_on_overlap`,
  `merge.compare_page_size`, `merge.compare_max_pages`, `merge.paths_shown`), generated module, `scripts/lib/merge_behind.py`
  (from BD1 #667, reviewed; reason reads "N behind, limit M"), `test_merge_behind.py`, `merge-behind.test.sh`, covers sidecar,
  CODEOWNERS via `scripts/generate`. Depends on 2.
- [ ] 4. `commit_check.rebase_errors` reads `merge.tier1_requires_base_merge` and `merge.max_behind_base`: on (default) today's
  refusal, now naming "N behind, limit 0"; off, a head behind by at most the limit passes and beyond it is refused with
  "N behind, limit M". FP1 (force-push/merge-commit rules) untouched. Tests in test_commit_check.py. Depends on 3.
- [ ] 5. `merge-phase`: proof from the v4 event log (`merge_behind.py evidence` over `forge_events.gate_evidence`, per PR channel
  and plan) instead of local `.pass` files; `merge.require_mergeable`, `merge.require_exact_head` (`--match-head-commit`) and the
  behind-base rule (`merge_behind.py behind`) read from the registry; `rest_fake.py` gains a `/compare/` route; merge-phase.test.sh
  emits gate.passed events through the fake forge. Depends on 3; independent of 4 (disjoint files).
- [ ] 6. retro.md.
- [ ] 7. Gate run 1 fixes (code): the other merge-phase caller (`test_claude_session.py`) emits its proof to the event log
  instead of a `.pass` record; merge_behind's reader producer no longer names the production entrypoint (production guard).
- [ ] 8. Gate run 1 fix (class): `test_hermetic` trace-directory test uses a private TMPDIR instead of the shared one that
  concurrent script tests write; INCIDENT in retro.md.

Critical path: 2 → 3 → 5 → gate → 6 (≈ 10 + 15 + 25 + gate + 10 min). 4 is off the critical path (disjoint files from 5);
run in sequence by the one writer because both are short.

## Premises
- P-47 (GA-PG3) CRITICAL, decided: default keeps today's rule; the relaxation is one registry key (`scripts/config`), never a literal.
- P-18 train sole merger (medium): merge-phase stays the current-rule merger, train.py not touched (GX-30 reads the keys).
- P-46 (GA-PG1) medium: the verdict of record is the pinned `scripts/gate-dev --pr 722`.
- New refusal in merge-phase (behind > limit or overlapping changes → re-gate) is BD1's reviewed rule; low blast radius,
  revert or raise the limit through the registry.

## Tests
3: `scripts/run test merge-behind`; 4: `scripts/run test commit-check`; 5: `scripts/run test merge-phase`; final: pinned
`scripts/gate-dev --pr 722`.

## Known base defects expected
KD-335a14a4, KD-71c8e5fe, KD-27b768cb, KD-a3870679, KD-41f822d3; env tests claude-session, root-identity, config (GX-ENV).
