import type { ProgressRow } from "../domain/rules.ts";

export interface ProgressWrite {
  readonly userId: string;
  readonly courseId: string;
  readonly lessonId: string;
  readonly durationSeconds: number;
  /** Already clamped to [0, durationSeconds]. */
  readonly positionSeconds?: number;
  readonly completed?: boolean;
}

/** No SQL. The server adapter is the only implementation that talks to `lesson_progress`. */
export interface ProgressRepositoryPort {
  read(userId: string): Promise<readonly (ProgressRow & { readonly courseId: string })[]>;
  save(write: ProgressWrite): Promise<boolean>;
}
