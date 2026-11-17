# Exceptions to `pnpm audit --audit-level high`

Rule (§10.2): high/critical vulnerabilities block CI. Every exception must have an owner, deadline, and reason, and must appear both here and in `apps/web/package.json` → `pnpm.auditConfig.ignoreGhsas`. The test in `apps/web/test/meta/audit-exceptions.test.ts` fails if the lists differ or an owner/deadline is missing.

| GHSA | Package | Dependency path | Reason | Owner | Deadline |
|---|---|---|---|---|---|
| GHSA-vfj7-8cjw-p6xm | `braces` ≤ 3.0.3 (no fixed version as of 8 Oct 2026) | dev: `eslint-config-next` → `@next/eslint-plugin-next` → `fast-glob` → `micromatch` → `braces` | Recursive DoS through attacker-supplied nested brace patterns. Used only by lint in development/CI with glob patterns from our own configuration; absent from runtime and client bundles. No fixed version is available for an override. | Engineering (implementing agent) | Reassess at every phase gate; remove as soon as a fixed `braces` release or `@next/eslint-plugin-next` without `fast-glob` is available. Final deadline: F13 gate. |
