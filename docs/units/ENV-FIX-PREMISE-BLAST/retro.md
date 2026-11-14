# ENV-FIX-PREMISE-BLAST — retro

1. **Brief.** Clear. One correction: fixing the producer alone would not have unblocked the store. `premise.*` v1 is in
   `forge-events.subject_exempt_schemas`, so `event_contracts.validate` refuses it on read whatever its producer
   ("predates the port"). The reader's quarantine is the fix; the producer change and the publish check stop the
   class at the source.
2. **Root cause class.** A hand-built envelope (`premises.event`) bypassed `ForgeEvents.build`, and the store reader
   treated any refused entry of an append-only log as fatal. A permanent, shared failure from one bad write.
3. **Execution.** 5 commits. The first push of the unit needed `OU_CONFIG_STORE=file` for the pre-push hook (the hook
   itself reads the store); from commit 3 on, the push ran with the default store.
4. **Gate.** Run 1 on `8db14e03` stopped in preflight (`env`: the vercel tree, left half-installed by the SessionStart
   setup that ran while `config.get` raised; `setup.sh` again repaired it). Run 2 was red `code`: generated drift (a new
   registry key needs `scripts/generate python-types`), the literal census on the new test, and the plan's missing
   effort block; `push-guard.test.sh` failed once under the gate's load and passed alone. Final run in the PR STATUS.
5. **Lessons.**
   - (a) Every reader of an append-only log must survive one bad entry: skip, quarantine, say it. Owner: engine-events
     (`ForgeEvents.read` callers other than config still collect `rejected`; none raises today).
   - (b) A producer that builds envelopes by hand validates the envelope before append. Owner: engine-premises (done).
   - (c) Registry values that end up in a contract field get a test against that contract's pattern (done for
     `*producer`).
