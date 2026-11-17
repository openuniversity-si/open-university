import { createDatabaseClient } from "../../scripts/lib/database-client.ts";
import type { SqlClient } from "./repository.ts";

export interface ToolingConnection extends SqlClient {
  end(): Promise<void>;
}

/** Plain Postgres to tower_tooling. */
export async function connectTooling(connectionString: string, options: { readonly readOnly: boolean }): Promise<ToolingConnection> {
  const client = createDatabaseClient(connectionString, options.readOnly);
  // A dropped idle session emits "error"; surface it on the next query instead of crashing the process.
  let failure: unknown = null;
  client.on("error", (error: unknown) => { failure = error; });
  await client.connect();
  return {
    async query(text, values) {
      if (failure !== null) throw failure instanceof Error ? failure : new Error("tower_tooling connection failed.");
      const parameters = values ? [...values] : [];
      const result = await client.query(text, parameters);
      return { rows: result.rows as Record<string, unknown>[] };
    },
    end: () => client.end(),
  };
}

/** Read a required variable without ever echoing its value. */
export function requiredEnv(name: string, purpose: string, env: Readonly<Record<string, string | undefined>> = process.env): string {
  const value = env[name];
  if (!value) throw new Error(`${name} is not set; it is required ${purpose}. See docs/fidelity/F03.md.`);
  return value;
}

const SECRET_VARIABLES = [
  "TOWER_TOOLING_DATABASE_URL", "TOWER_TOOLING_DATABASE_URL_OWNER", "TOWER_TOOLING_DATABASE_URL_POOLED",
  "FIGMA_TOKEN",
  "R2_ACCESS_KEY_ID_RW", "R2_SECRET_ACCESS_KEY_RW", "R2_ACCESS_KEY_ID_RO", "R2_SECRET_ACCESS_KEY_RO",
] as const;

/** Error text safe for logs: secret values and connection strings are redacted. */
export function safeErrorMessage(error: unknown, env: Readonly<Record<string, string | undefined>> = process.env): string {
  let message = error instanceof Error ? error.message : String(error);
  for (const name of SECRET_VARIABLES) {
    const value = env[name];
    if (value) message = message.split(value).join(`[${name}]`);
  }
  return message.replace(/postgres(?:ql)?:\/\/\S+/g, "[redacted connection string]");
}

/** One short session per call: connect, run, always close. */
export function toolingSessions(connectionString: string, options: { readonly readOnly: boolean }) {
  return async <T>(work: (db: SqlClient) => Promise<T>): Promise<T> => {
    const db = await connectTooling(connectionString, options);
    try {
      return await work(db);
    } finally {
      await db.end();
    }
  };
}
