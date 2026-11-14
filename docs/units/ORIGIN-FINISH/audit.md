# ORIGIN-FINISH — audit

Base: `mod/roadmap-integration` at `98cf1db5` (02/11/2026). Read-only, cheap evidence: no suite was run. Commands are
run from the repository root unless they say `scripts/lib`.

## Entradas
- [intake.md](intake.md): the operation still selects GitHub; resolved when every GitHub dependency is counted, the
  removable ones are removed, and the switch to Origin is one operator step whose readiness the engine checks.
- [research.md](research.md): mirror, then flip one selector behind a readiness check; never a fallback.

## Findings

### The coordinator's leads, measured again
- **L1. Baseline calls: 4, not 9.** `scripts/lib/adapters/engine-vendors.json` lists four GitHub baseline sites:
  `scripts/cloud/setup.sh:gh` (cli-version), `scripts/lib/credentials.py:github_api` (credential-probe),
  `scripts/lib/release_policy.py:github_api` (origin-url), `scripts/lib/toolchain_manifest.py:github.com`
  (artifact-hosting). `vendor_check.check(root, None)` returns 0 errors, 0 warnings. Later merges closed the others.
- **L2. Port operations: Origin implements all 23.** `cd scripts/lib && python3 operation_demands.py`:
  `github: 23 proven`, `origin: 23 proven`, `confrontation: 0 finding(s)`. The 18th operation of the lead
  (`pushes`/`force_pushes`) landed with #1081 (`0dbff03a`). A "proof" is an AST check that a named test calls the
  operation (`operation_demands.py:117-145`); it runs nothing.
- **L3. The journal is on the control plane.** `forge-events.log_adapter` = `control`. Holds.
- **L4. The operation runs on GitHub.** `forge-events.adapter` = `github` (registry default; no override in the store).

### What the baseline does not count (GitHub calls outside the adapters)
- **F1. Seven calls run GitHub's shim by its file path from Python, and the vendor check does not see them.**
  `vendor_check` recognizes a module by import, or by its `.py` file named in shell or JavaScript; a Python argv
  `[sys.executable, …/'github_cli.py', …]` is neither. Sites:
  - `scripts/lib/gate_pin.py:95-106` `pr_identity` (`pr view`): the `--pr` gate pin and `gate_verdict.py:209`.
  - `scripts/lib/gate_explain.py:45` (`pr view`, `gate-dev --explain`).
  - `scripts/lib/merge_behind.py:68-71` (`api repos/{repo}/compare`), its CLI takes `--github-cli`.
  - `scripts/lib/lane_ship.py:106` (`POST repos/{repo}/pulls`) and `:238` (`GET repos/{repo}/pulls/{n}`).
  - `scripts/lib/lane_status.py:103` (the comments of issue `forge-events.github_log_issue`).
  - `scripts/lib/decision_next.py:42` (open pull list).
- **F2. GitHub's pull ref namespace.** `refs/pull/{n}/head` is read by `scripts/lib/service_runner.py:41,89-94` (the
  runner's stale-job check), `scripts/lib/gate_attested.py:87` and `scripts/lib/gate_bypass.py:82`. The port has no
  operation that names a change's head ref; whether Origin publishes `refs/pull/*` is unknown (no live Origin here).

### What selects GitHub without the selector
- **F3. The board.** `scripts/lib/forge_events.py:313` builds `construct_adapter('github', {'issue_comments'})`
  whatever `forge-events.adapter` says. Dormant today: `forge-events.board_issue` = 0.
- **F4. The config store lives on a GitHub issue.** `config.store_adapter` = `github` (enum `file`, `github`;
  `config/registry/config.json`), and `config.store()` (`scripts/lib/config.py:320-331`) builds that adapter by name.
  The store holds 5 live overrides (`coordinator.max_sessions`, `gate.bypass`, `providers.model_ladder`,
  `service.paused`, `train.trigger_mode`), so every operator switch, including `forge-events.adapter`, is written
  to and read from GitHub.
- **F5. Origin's merges and locks go to the checkout's git remote.** `OriginAdapter` builds `GitRefs()`
  (`scripts/lib/forge_origin.py:61`), whose remote is `train.git_remote` = `origin`; here `git remote get-url origin`
  = `https://github.com/openuniversity-si/open-university`. The only guard (`forge_origin.py:63`) checks that the URL ends with
  `/openuniversity-si/open-university`, which the GitHub URL passes. With the selector on `origin` in a GitHub clone, the API reads
  would be Origin's and every merge and lock push GitHub's: a hidden dual path.

### Credentials and reach
- **F6. The preflight checks GitHub, whatever the forge.** `scripts/lib/preflight.py:146` calls
  `missing_credentials(('github', 'neon', 'vercel'), …)`; `credentials.PROVIDERS` has no Origin entry, and the
  GitHub probe is `github_api.ping()` (`credentials.py:142-146`, baseline site). With the selector on `origin`,
  preflight would pass on a machine that has no `origin` CLI and no Cursor key.
- **F7. Origin is not reachable from this session.** `curl https://api.cursor.com/` → `CONNECT tunnel failed,
  response 403`; no `origin` on PATH; no `CURSOR_API_KEY`/`CURSOR_AUTH_TOKEN`. The live suite
  `test_forge_origin_live.py` is skipped without `OU_ORIGIN_LIVE` and covers four read operations only; no write
  operation and no `_run_cli` transport has run against the real API in the repository's evidence.
- **F8. The control plane requires GitHub's webhook secret.** `services/control-plane/src/core.js:719-723`
  (`missingSecrets` names `GITHUB_WEBHOOK_SECRET`, `/readyz` answers 503 without it).

### Dead code
- **F9. `release_policy.py merge` has no caller.** The CLI's `merge` subcommand (`release_policy.py:66-68`), the
  GitHub baseline site, served `merge-phase`, which left the repository; `rg "release_policy.py"` finds no caller
  and `test_release_policy.py` never runs it.

### Also seen (not this unit's)
- `train_reuse.verified_source` needs an adapter with `trusted` (`train_reuse.py:41-47`), which only GitHub's has; with
  `log_adapter` = `control` reuse already finds no verified source. Not a GitHub dependency; the reuse owner's.

## Causas raiz

### R1. The vendor check cannot see a Python process that runs a vendor's module by path
Cadeia de porquês:
1. Por que o baseline diz 4 quando há 11 chamadas ao GitHub fora dos adapters? Seven of them (F1) are not detected.
2. Por que não são detectadas? The module detector matches imports and a `.py` file named in shell or JavaScript; a
   Python argv string `'github_cli.py'` or a path built with `/` is neither (`vendor_check.py` docstring, `module`).
3. Por que existe essa forma de chamada? The shim was the subprocess client of the old delivery tail, and its callers
   kept the subprocess form when the tail moved to Python.
4. Por que nada recusou essas chamadas? The shrink-only baseline is only as good as the detector, and no test feeds the
   detector the subprocess form.
Classe: mecanismo faltando
Evidência: F1; `scripts/lib/vendor_check.py` (module detection); `engine-vendors.json` baseline of 4.

### R2. The forge is selected per concern, not once
Cadeia de porquês:
1. Por que mudar `forge-events.adapter` não tira o GitHub da operação? The board, the config store and the git remote of
   the Origin adapter do not read it (F3, F4, F5).
2. Por que não o leem? Each was built when GitHub was the only forge: the board names `github`, the store has its own
   key with `github` as the only remote value, and the git remote was taken to be the forge's without a check.
3. Por que nada impede uma segunda seleção? D-283 says no module branches on the vendor, but no check refuses a literal
   adapter name passed to `construct_adapter`, and the Origin adapter does not assert that its git remote is Origin's.
Classe: arquitetura/desenho
Evidência: `forge_events.py:313`; `config.py:320-331`; `forge_origin.py:61-64`.

### R3. Nothing checks that the selected forge can run before the operation runs on it
Cadeia de porquês:
1. Por que a preflight passaria numa máquina sem o CLI do Origin? It checks GitHub's credential only (F6).
2. Por que só o do GitHub? `credentials.PROVIDERS` is a list of vendors, written before a second forge existed; the
   forge credential is not derived from the selector.
3. Por que isso importa para a virada? The switch is an operator step; without a readiness check of the selected
   forge, the first sign of a gap is a failed train run.
Classe: mecanismo faltando
Evidência: `preflight.py:146`; `credentials.py:142-210`.

### R4. Origin is not part of any environment the operation runs in
Cadeia de porquês:
1. Por que nenhum PR correu no Origin? No environment of the operation can reach it (F7): no CLI, no key, egress refused.
2. Por que não? The toolchain manifest pins `gh` and not the `origin` CLI, the environments' secrets name GitHub only,
   and the egress allowlists were set for GitHub.
3. Por que o repositório não sabe disso? The environments are configured outside the repository, and whether the
   repository exists on Origin (its home) is a source-of-truth question no file records.
Classe: arquitetura/desenho
Evidência: F7; `config/registry/toolchain.json` (no origin entry); session egress probe.

### R5. The engine names a change's head by GitHub's ref namespace
Cadeia de porquês:
1. Por que o runner e o gate leem `refs/pull/N/head`? To get a PR's head with one git call and no REST (F2).
2. Por que é um nome do GitHub? The namespace is GitHub's convention; the port has no operation that returns a change's
   head ref by forge-neutral means.
3. Por que não foi trocado? The head sha is available from `port.change`, but these sites wanted a git-only read to
   save the REST budget.
Classe: arquitetura/desenho
Evidência: `service_runner.py:41,89-94`; `gate_attested.py:87`; `gate_bypass.py:82`.

## Distância do estado da arte
We have the single selector, the port, an Origin adapter with every operation, and the journal off GitHub. Missing: a
truthful count of the GitHub calls (R1), one selection for every concern (R2), a readiness check of the selected forge
(R3), an environment that reaches Origin (R4) and forge-neutral head refs (R5). The escada's first rung is R1–R3 inside
the repository; R4 is outside; R5 and the config store's move are the next units.

## Base defects expected
None known on the files this unit touches. The gate's D-151 bypass does not run the suites, so the touched suites are
run by hand.
