# TOOLCHAIN-ATTEST-STORE: retro

- **Worked:** the root cause was one line (`values.update(config.overrides())` in `registry_digest`); the fix and its three proofs fit one commit; #808 files untouched (only DECISIONS.md, appended D-080).
- **Cost:** gate round 1 refused the audit (Padrão v6 `## Entradas` / `## Distância do estado da arte`) and the missing effort block; the literal census refused date and length literals in the test.
- **Lesson:** an identity that gates admission must hash committed inputs only; any runtime-store read inside it is a split-brain between the gate and the train. Next rung: hash only the owners that are toolchain inputs, so an unrelated committed parameter change does not void every open verdict.
- **Follow-up:** verdicts made before this merge carry the old id and keep falling back once; the first gate after the merge attests the new one.
