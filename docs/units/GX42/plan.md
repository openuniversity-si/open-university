# GX-42 plan (audit folded in)

Audit: plan.md `program.v1` block is lines 496-541 on base 4bc4dd04; plan-v2 §6.1 block is lines 265-314 of plan-v2.md (origin/mod/ga4 bce2cd94); plan-v2.md is not on the base. `scripts/program check` exists.

Critical path (about 10 min): plan-v2.md copy -> block splice -> check. All edges are real; files are disjoint, so no fan-out is worth its cost.

1. Bring plan-v2.md in byte-identical (`git checkout origin/mod/ga4 -- ...`).
2. Replace the block in plan.md and add one pointer line.
3. This audit and plan.
4. RETRO.

Premises: GA-P01..GA-PG3 (P-42..P-47), docs only, low; none CRITICAL.
Tests: `scripts/program check gate-excellence`, block diff empty, `cmp` of plan-v2.md with origin/mod/ga4. Final: gate-dev from a base-tip checkout.
Known base failures: claude-session, root-identity, config (RegistryMemo) script tests; owner GX-ENV.
