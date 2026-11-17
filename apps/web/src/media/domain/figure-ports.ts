export interface LifecycleObject {
  readonly sha256: string;
  readonly bytesPresent: boolean;
  readonly referenced: boolean;
  readonly retainedRelease: boolean;
  readonly orphanedAt: string | null;
}

export interface EnvironmentInventory {
  readonly environment: "prod" | "preview";
  readonly complete: boolean;
  readonly references: readonly LifecycleObject[];
}

export interface LifecycleEnvironment {
  readonly name: "prod" | "preview";
  listInventory(): Promise<EnvironmentInventory>;
  markOrphan(sha256: string): Promise<"marked" | "already" | "referenced">;
  clearOrphan(sha256: string): Promise<void>;
  barrier(): Promise<boolean>;
  revalidate(): Promise<boolean>;
  snapshot(): Promise<{ id: string; checksum: string; rows: number } | null>;
  restore(snapshotId: string): Promise<boolean>;
  reset(): Promise<boolean>;
  rehearse(snapshotId: string): Promise<boolean>;
  deleteRow(sha256: string): Promise<boolean>;
}

export interface StoragePage {
  readonly keys: readonly string[];
  readonly cursor: string | null;
  readonly complete: boolean;
}

export interface LifecycleStorage {
  list(cursor: string | null): Promise<StoragePage>;
  copyAside(sha256: string): Promise<boolean>;
  remove(sha256: string): Promise<boolean>;
  exists(sha256: string): Promise<boolean>;
}

export interface LifecycleJobs {
  claim(generation: string): Promise<{ acquired: boolean; token: string }>;
  receipt(token: string, sha256: string): Promise<void>;
  complete(token: string, error?: string): Promise<void>;
}

export interface LifecycleDeps {
  readonly environments: readonly ["prod", "preview"];
  readonly now: () => Date;
  readonly ports: Readonly<Record<"prod" | "preview", LifecycleEnvironment>>;
  readonly storage: LifecycleStorage;
  readonly jobs: LifecycleJobs;
}

export interface LifecycleInventoryReport {
  readonly generation: string;
  readonly complete: boolean;
  readonly references: readonly Readonly<{ sha256: string; prod: boolean; preview: boolean; retainedRelease: boolean }>[];
}

export interface GcReport {
  readonly generation: string;
  readonly marked: number;
  readonly deleted: number;
  readonly skipped: number;
}
