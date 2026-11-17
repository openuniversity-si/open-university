import { describeViolation, type NoVideoRecord, type NoVideoViolation } from "../../e2e/fixtures/no-video-policy.ts";

export const SELFTEST_FILE_SUFFIX = "no-video-guard.selftest.spec.ts";

function isRequestTo(violation: NoVideoViolation, domain: string): boolean {
  if (violation.kind !== "request") return false;
  const host = URL.parse(violation.url)?.hostname ?? "";
  return host === domain || host.endsWith(`.${domain}`);
}

export interface NoVideoSummary {
  readonly ok: boolean;
  readonly lines: readonly string[];
}

/**
 * Consolidates the per-test records written by the guard fixture (ADR-11):
 * - every regular test must have zero violations;
 * - the self-tests must exist and have recorded every violation kind,
 *   proving the guard was active in this run.
 */
export function summarizeNoVideoRecords(records: readonly NoVideoRecord[]): NoVideoSummary {
  const lines: string[] = [];
  const regular = records.filter((r) => !r.file.endsWith(SELFTEST_FILE_SUFFIX));
  const selftests = records.filter((r) => r.file.endsWith(SELFTEST_FILE_SUFFIX));
  let ok = true;

  const offenders = regular.filter((r) => r.violations.length > 0);
  const requests = regular.reduce((n, r) => n + r.violations.filter((v) => v.kind === "request").length, 0);
  const plays = regular.reduce((n, r) => n + r.violations.filter((v) => v.kind !== "request").length, 0);
  lines.push(`verify:no-video: ${String(regular.length)} test record(s); ${String(requests)} video request(s); ${String(plays)} play() call/event(s).`);

  if (regular.length === 0) {
    ok = false;
    lines.push("FAIL: no test records found; run pnpm e2e and pnpm a11y first.");
  }
  for (const record of offenders) {
    ok = false;
    lines.push(`FAIL: [${record.project}] ${record.title}: ${record.violations.map(describeViolation).join("; ")}`);
  }

  const misplacedSelftests = selftests.filter((r) => r.expectedStatus !== "failed");
  for (const record of misplacedSelftests) {
    ok = false;
    lines.push(`FAIL: self-test not marked as expected failure: ${record.title}`);
  }
  const silentSelftests = selftests.filter((r) => r.violations.length === 0);
  for (const record of silentSelftests) {
    ok = false;
    lines.push(`FAIL: guard self-test recorded nothing: [${record.project}] ${record.title}`);
  }
  const selfViolations = selftests.flatMap((r) => r.violations);
  const coverage = {
    "mux.com request": selfViolations.some((v) => isRequestTo(v, "mux.com")),
    "litix.io request": selfViolations.some((v) => isRequestTo(v, "litix.io")),
    "play() call": selfViolations.some((v) => v.kind === "play-call"),
    "play event": selfViolations.some((v) => v.kind === "play-event"),
  };
  const missing = Object.entries(coverage).filter(([, seen]) => !seen).map(([name]) => name);
  if (missing.length > 0) {
    ok = false;
    lines.push(`FAIL: guard self-tests did not prove rejection of: ${missing.join(", ")}.`);
  } else {
    lines.push(`guard self-test: ${String(selftests.length)} expected rejection(s) recorded (mux.com, litix.io, play() call, play event).`);
  }

  lines.push(ok ? "verify:no-video: PASS" : "verify:no-video: FAIL");
  return { ok, lines };
}
