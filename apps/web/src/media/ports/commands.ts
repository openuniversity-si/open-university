export interface CoverDescriptor { readonly sha256: string; readonly url: string; readonly width: number; readonly height: number }
export interface CoverRow extends CoverDescriptor {
  readonly ownerId: string; readonly kind: string; readonly variant: string; readonly version: number;
}
export interface MediaCommandsPort {
  covers(owners: readonly { readonly owner: "course" | "lesson" | "subarea"; readonly id: string }[]): Promise<readonly CoverRow[]>;
  validateObject(cover: CoverDescriptor & { readonly mediaSha256?: string }): Promise<string | null>;
  queuePending(input: { readonly keys: readonly string[]; readonly rows: readonly { readonly pathname: string; readonly owner?: string; readonly ownerId?: string }[]; readonly courseId: string; readonly requestId: string }): Promise<void>;
  usedKeys(keys: readonly string[]): Promise<readonly string[]>;
  diagnose(catalog: { readonly courseIds: readonly string[]; readonly lessonIds: readonly string[]; readonly covers: readonly { readonly id: string; readonly sha256: string | null; readonly width: number | null; readonly height: number | null; readonly pathname: string | null; readonly url: string | null }[] }): Promise<readonly { readonly code: string; readonly count: number; readonly sample: readonly unknown[] }[]>;
  pending(filter: { readonly courseId?: string; readonly lessonId?: string }): Promise<readonly string[]>;
  drain(store: () => { delete(key: string): Promise<void> }, filter: { courseId: string } | { lessonId: string }, checkedKeys: readonly string[]): Promise<{ deleted: string[]; pending: string[] }>;
}
