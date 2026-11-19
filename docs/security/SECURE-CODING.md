# Secure coding standard

The secure coding practices of this repository (SSDF PW.5, `config/security/controls/CTRL-ssdf-pw.5.json`). Each
practice names what enforces it; a practice with no enforcement says so. It covers the engine's Python and shell and
the site's TypeScript (`apps/web`). It adds no review step (D-055): what is enforced is enforced by the gate.

## Every language

1. **No secret in the tree.** Credentials, tokens and database URLs live in the environment or the provider's secret
   store, never in code, configuration or records. Enforced: the gate's secret scans of the tree and of the history
   (`STD-gate-secret-scan-tree`, `STD-gate-secret-scan-history`), the local check before every push
   (`config/registry/local-checks.json`), and the registry's refusal of a secret-shaped value (`STD-config-value-errors`).
2. **Never print a secret.** A check names a missing credential, never its value. Enforced: `scripts/tests/test_preflight.py`.
3. **Parse at the boundary.** Input from outside (a request, a registry value, an event, a file) is parsed against its
   schema or type before it is used, and refused when it does not match. Enforced: the JSON contracts and
   `STD-json-schema-errors` in the engine; TypeScript's strict type check and the site's domain parsers (for example
   `parseTheme` in `apps/web/src/config/domain/documents.ts`) in the site.
4. **Least privilege.** A role, a token or a process gets only what its job needs (D-069 item 13). Enforced on AWS by
   the permissions boundary every role carries (`scripts/tests/test_infra_aws.py`, `test_every_role_carries_the_boundary`).
5. **Dependencies are pinned and audited.** A new package goes through the supply review; pins and checksums are
   checked (`CTRL-ssdf-pw.4`, `scripts/tests/supply.test.sh`).

## Python and shell (the engine)

6. **No injectable call.** No `shell=True` or `os.system` on a built string, no `eval`/`exec` of data, no unsafe
   deserialization (`pickle`, `yaml.load`, XML without a hardened parser), no disabled TLS check, no bound-to-all
   interface. Enforced: the lint ratchet keeps the ruff families of `rules.lint_select` (bugbear and the bandit `S`
   rules for these classes) at zero findings (`STD-lint-ratchet`).
7. **Git writes take literal messages.** A git write verb's `-m` takes a literal or an f-string, never a value built
   elsewhere. Enforced: `STD-repo-hygiene-argv-message-errors`.
8. **Shell scripts quote their expansions and run with `set -euo pipefail`.** Not enforced by a check yet (no shell
   linter is pinned in the toolchain).

## TypeScript (the site)

9. **No string runs as code.** No `eval`, `new Function`, `javascript:` URL or prototype tampering. Enforced:
   `apps/web/eslint.config.mjs` (`no-eval`, `no-new-func`, `no-script-url`, `no-proto`, `no-extend-native`,
   `react/jsx-no-script-url`, and the type-checked `@typescript-eslint/no-implied-eval`), run by `pnpm lint` in the
   required web check (`CHK-web`). Tests may feed `javascript:` URLs as hostile input.
10. **No unsafe `any`.** Values of unknown type are narrowed before use. Enforced: `@typescript-eslint/no-explicit-any`
    and the `no-unsafe-*` rules of `strictTypeChecked`.
11. **Links and frames.** A `target="_blank"` link carries `rel="noreferrer"`; an iframe carries a `sandbox`. Enforced:
    `react/jsx-no-target-blank`, `react/iframe-missing-sandbox`.
12. **Raw HTML only from a parsed value.** `dangerouslySetInnerHTML` takes only a value its parser has bounded (the
    one use, the theme block of `apps/web/src/app/layout.tsx`, comes from `parseTheme`, which refuses `;{}<>` and line
    breaks). Not enforced by a rule yet: `react/no-danger` would flag that one use and needs a justified disable first.
13. **Database access through the query builder.** SQL is built by Drizzle with bound parameters, never by string
    concatenation of input. Not enforced by a rule; the integration suite runs the handlers on real PostgreSQL.
14. **Cookies are `HttpOnly`, `SameSite=Lax` and `Secure` over HTTPS.** Enforced: `apps/web/test/int/auth.int.test.ts`
    (the session cache cookie is `HttpOnly`); the attributes are set in `apps/web/src/identity/server/config.ts`.
