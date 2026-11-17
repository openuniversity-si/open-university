/**
 * The database handle the session receives.
 * The production pool already fulfills this. The driver stays in the pool module.
 */
export interface SessionConnection {
  query(sql: string, values?: unknown[]): Promise<{ rows: Record<string, unknown>[]; rowCount?: number | null }>;
  release(): void;
}

export interface SessionDatabase {
  query(sql: string, values?: unknown[]): Promise<{ rows: Record<string, unknown>[]; rowCount?: number | null }>;
  connect(): Promise<SessionConnection>;
  end(): Promise<void>;
}
