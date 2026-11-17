export interface OperationalSlis {
  readonly activeReleaseNumber: number;
  readonly projectionCount: number;
  readonly projectionDriftCount: number;
  readonly pool: Readonly<{ total: number; idle: number; waiting: number }>;
  readonly lastPublishDurationMs: number | null;
  readonly scope: "process";
}

export interface OperationalSliSources {
  activeReleaseNumber(): Promise<number>;
  projectionCount(): Promise<number>;
  projectionDriftCount(): Promise<number>;
  pool(): Readonly<{ total: number; idle: number; waiting: number }>;
}

let publishStarted: number | null = null;
let lastPublishDurationMs: number | null = null;

/** Marks the start of a publish. The duration is stored only after commit. */
export function markPublishStart(now = Date.now()): void {
  publishStarted = now;
}

export function recordPublishCommitted(now = Date.now()): void {
  lastPublishDurationMs = publishStarted === null ? null : now - publishStarted;
  publishStarted = null;
}

export function lastPublishDuration(): number | null {
  return lastPublishDurationMs;
}

/** Public health signal. Missing samples stay unknown and never look like a healthy zero. */
export function publicDiagnostics(): "ok" | "unknown" {
  return lastPublishDurationMs === null ? "unknown" : "ok";
}

export async function collectOperationalSlis(sources: OperationalSliSources): Promise<OperationalSlis> {
  const [activeReleaseNumber, projectionCount, projectionDriftCount] = await Promise.all([
    sources.activeReleaseNumber(), sources.projectionCount(), sources.projectionDriftCount(),
  ]);
  return {
    activeReleaseNumber, projectionCount, projectionDriftCount,
    pool: sources.pool(), lastPublishDurationMs, scope: "process",
  };
}
