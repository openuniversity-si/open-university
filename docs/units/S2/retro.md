# S2 retro

## 1. Brief quality
Clear on scope. Gaps: no role list for the key scopes (roles invented: coding-agent, coordinator, gate-runner, release-tail); the brief named branch `mod/motor-s2-supply-chain` while the session designated `claude/supply-chain-allowlist-gjngok` (the designated one was used); "resolves from a registry" is undefined for a lockfile v9 with no tarball URLs (all 585 entries are implicit, so the `.npmrc` / default registry is checked).

## 2. Audit and plan
Held: C0 registry and T1 check are reusable as merged; check-architecture reads only `packages` and `retired`, so `transitive` is safe. Broke: the config guard rejects any key containing "secret" unless it holds one env name, so the name lists became `grantable_env_names` and `refused_env_names`. Plan unchanged otherwise (6 commits).

## 3. Execution
One failure class: the config guard (above), found by structure-check before the commit, fixed in one rename. No rework, no dead ends. Work was sequential (shared files), so no sub-agents.

## 4. Gate
Run 1 on 3c3928a8 (base merged at launch): 890 s, exit 1, only the script-tests stage. Failures, none in S2 files: `gate-heavy-db.test.sh` (heavy-slot wait under load, timing), `generate.test.sh` (intents-doc.ts ERR_MODULE_NOT_FOUND in the gate checkout), `premises.test.sh` (register answer `measurement:S1`, fixed on base by engine-premises after launch). Stages: script tests 667.6 s, structure check 77.7 s, secret scan history 8.0 s, schema compat 3.4 s, secret scan tree 3.2 s, generated drift 0.6 s, no workflows 0.02 s. Action: merged the newer base and re-gated; the result of run 2 is in the PR comment.

## 5. Lessons
- Brief template: list agent roles for key-scope units, owner: coordinator (CO1).
- Config guard error is discoverable only by running structure-check; document the "secret key must hold one name" rule in the registry README, owner: engine-config.
- The gate checkout lacks node deps for generate.test.sh; owner: engine-generate.
