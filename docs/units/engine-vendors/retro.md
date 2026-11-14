# engine-vendors retro (U4)

1. **Brief quality.** The brief asks for a move into `units/engine-vendors/` and a manifest `contract`, but UNITS.md (U3a) says
   a `scripts/` unit has no `@ou` address and S1 keeps units logical; the brief's own fallback (keep in place) applied. It did
   not say that `unit-battery`'s contract step needs an address, so a manifest `contract` cannot be filled for any engine unit.
   The brief also named branch `mod/u4-engine-vendors` while the session was assigned `claude/u4-engine-vendors-oupvm5`.
2. **Audit and plan.** P-03 held (no move). P-05 held: `config_check.literal_findings` reports nothing for the unit and no
   `x-literal-sites` names it. The plan's commit 4 changed: the manifest contract was dropped after the battery went red on
   it (see 3); the contract lives in the entry docstring plus `test_ports_contract.py`.
3. **Execution.** Only real failure: battery 73.5 s over `battery.unit_time_limit`. Root cause class: a unit test calling a
   repo-wide check owned by another unit (`config.check(ROOT)`, 66 s). Same pattern searched in the unit's other tests: none.
   Second failure: contract step red for lack of an address (class: a manifest slot whose checker needs a precondition
   engine units lack). Timeline: audit+plan commit, battery fix, contract test, base merge. No waits.
4. **Gate.** Run results are in the PR comment "Gate" (the head must not change after the gate).
5. **Lessons.**
   - Brief template: say whether the unit has an address and whether the manifest contract slot is usable (owner: coordinator).
   - `unit_battery` contract step: resolve the entry against the unit's home when there is no address, so engine units can
     publish a contract (owner: engine-battery).
   - Unit tests must not call another unit's repo-wide check; a lint for `config.check(` in tests of other units (owner: engine-hermetic-tests).


## Origin visibility regression (2026-11-02)

D-069 item 7 now includes the existing Origin forge implementation. Catalog count: 9 → 10.
Before and after: github active; github-actions forbidden; claude active; codex, cursor, neon,
vercel, cloudflare-r2 and figma slot. Added origin active, with no baseline sites and therefore
no baseline classifications needed. No existing status or baseline changed.

Indexed temporary probes reproduced the brief on d909f85f0: GitHub URL 2 errors, Origin URL
1 error attributed to cursor, Origin shell command 0 errors. Untracked probes return no findings
because engine_files uses git ls-files; the probes were indexed for measurement and removed afterward.
Afterward: Origin URL, Python argv and shell command each produce exactly 1 Origin refusal;
the Cursor agent URL still produces exactly 1 cursor refusal. The committed fixtures cover these
formats, independent URLs in one string/line, reversed catalog ordering, both adapters, module
imports, and the selector's import-only permission. GitHub retains its two overlapping endpoint hits.

The actual repository scan, including against d909f85f0, returns ([], []): no real Origin call
outside the declared adapters was found. Both forge_origin.py and forge_origin_client.py are
adapters; forge_events.py is a selector. The new-vendor registration rule recognizes these files
because they already exist at the base; it still rejects new out-of-directory files and additions
to existing vendors. The baseline rule is unchanged and tested independently. No contract change:
contracts/adapters/engine-vendors.v1.json and its ownership manifest remain untouched.

Validation, with OU_CONFIG_STORE=file:
- PYTHONPATH=scripts/lib/hermetic bash scripts/tests/vendor-ports.test.sh: all 49 tests pass.
- PYTHONPATH=scripts/lib/hermetic python3 scripts/lib/commit_check.py --local: 0 refusals.
- bash scripts/structure-check: 0 errors, 17 warnings before and after; complete warning lists identical.
- PYTHONPATH=scripts/lib/hermetic bash scripts/structure-check: 2 existing errors and 15 warnings
  before and after; complete FAIL/WARN lists identical. Besides the brief's FORGE-PORT audit R2,
  docs/units/R1/plan.md has a Requirement naming train rather than an owner. Neither was changed.

The native structure result lifts those two locks under the existing exception regime; its green
exit is not a claim that the hermetic judges passed. No bypassed gate is used as battery evidence.
