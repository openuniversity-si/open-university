# TX23 retro

## Brief quality
Clear and measurable (goal, files, DONE list with the mutation premise). Two gaps: the brief says "OWN only these three tests" but `scripts/tests/test_gate_report_v4.py` imports `SeamPayload.BEFORE_SPLIT` from one of them, so the pin had a second reader that the brief and the audit did not list; and the brief's "pinned hash" framing hid that only the verdict `input_hash` moves with the stage registry.

## Premises
- P-46 (T2) held: the three tests no longer list stages, selections or the modules set; the temporary stage and test additions in `evidence.md` pass the new tests and fail the base ones.
- The CRITICAL premise held: 12 mutations (4 areas, 4 report skips, 4 script tests), each failing the base test and the new test.
- Broken: "the code under test is the only thing the pin protects". `BEFORE_SPLIT` also protected `gate_report_v4`'s v3-stays-byte-identical tests.

## Failures and root-cause class
1. `gate-report-skips.test.sh` errored (2 errors) after removing `BEFORE_SPLIT`: class **hidden coupling** (a test constant read by a second test file). Fixed in the same commit by keeping the name as the computed digest, which also removes the pin for that reader; `grep -rn BEFORE_SPLIT` finds no other reader.
2. My first stage-add demo for `test_gate_areas.py` failed for both versions: class **incomplete experiment** (`subjectInstallUnless` is a second registry list that must also name the stage). Redone with it; the test side needs nothing else.

## Gate runs
The pinned `scripts/gate-dev --pr 749` on the final head is run once at the end; its result and head sha are in the MERGE-READY comment.

## Lessons
- A pinned constant that another test imports is a T2 violation twice over. Rule: when a unit removes a pin, `grep -rn <name>` across `scripts/` first and name every reader in the audit. Owner: TX-program audit template (TX-program lead).
- Registry lists that must stay in step (`order`, `always`, `subjectInstallUnless`, `gate_policy.PREREQUISITES`) are four edits per added stage; a derived check that names the lists that disagree would turn #732-style stage additions into one edit. Owner: TX20 (gate_areas code under test).
