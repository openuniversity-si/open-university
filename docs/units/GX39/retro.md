# GX-39 RETRO

## 1. Brief quality
- Clear scope and a precise file list. Gaps: the brief names `mod/gx39` while the session was bound to `claude/gx39-report-cache-seams-uabres` (used the latter, no second branch); "publish condition and channel `:233-234`" cites base lines that are now `main`/`emit_evidence`, resolved by reading the code; "identical v3 payload before/after" needs a fixture, so the test pins a digest taken from the pre-split code.
- The brief says GX-38 pre-claims new files, but GX-38 was unmerged when this ran, so structure-check fails ("production file of no unit") on this head until GX-38 merges.

## 2. Audit and plan
- Held: tests only touch `gate_report` names, so keeping the public names (wrappers `defect_events`, `adjudicate_known_defects`) kept every test unchanged. Registry reads stayed in `gate_report`, no `x-readers` change.
- Changed: `gate_tier` moved from commit 4 to commit 3 (the new modules import it). No fan-out: ~300 lines in two files, one writer was faster.

## 3. Execution
- Class failure: the literal census scans tracked files only, so my first `--write` (new files untracked) dropped the moved `1000` allowance instead of moving it. Fixed in one extra commit after tracking the files; verified 0 structure errors against GX-38's manifest. Prevention: `literal_census --write` should include untracked files or refuse with untracked production files (owner: engine-literals).
- Test literals (1.5, 3) tripped the census; rewrote the fixture without new numbers.
- Digest recomputed once after changing the fixture, from a throwaway worktree of the base.

## 4. Gate
See the PR comments for the own-checkout (report-only) and base-tip (verdict of record) runs and known env failures.

## 5. Lessons
- Prep units that add files should either merge after the manifest unit or carry their own manifest claim: brief template / coordinator launch order.
- `literal_census --write` with untracked files (above).
