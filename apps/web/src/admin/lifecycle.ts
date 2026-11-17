import type { LifecycleDeps } from "../media/domain/figure-ports.ts";

export interface PreviewResetReport {
  readonly dryRun: boolean;
  readonly snapshotId: string | null;
  readonly verified: boolean;
}

/** Zero the preview. Production is refused. The thirty-day exit is not this act. */
export async function resetPreviewEnvironment(deps: LifecycleDeps, opts: { dryRun: boolean; environment?: "prod" | "preview" }): Promise<PreviewResetReport> {
  const preview = deps.ports.preview;
  if (opts.environment === "prod" || preview.name !== "preview") return { dryRun: true, snapshotId: null, verified: false };
  if (opts.dryRun) return { dryRun: true, snapshotId: null, verified: false };
  const suspended = await preview.barrier();
  if (!suspended) return { dryRun: false, snapshotId: null, verified: false };
  const snap = await preview.snapshot();
  if (!snap?.checksum || snap.rows < 0) return { dryRun: false, snapshotId: null, verified: false };
  const rehearsed = await preview.rehearse(snap.id);
  if (!rehearsed) return { dryRun: false, snapshotId: snap.id, verified: false };
  const cleared = await preview.reset();
  if (!cleared) {
    await preview.restore(snap.id);
    return { dryRun: false, snapshotId: snap.id, verified: false };
  }
  return { dryRun: false, snapshotId: snap.id, verified: true };
}
