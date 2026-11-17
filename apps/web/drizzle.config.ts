import { defineConfig } from "drizzle-kit";

// Generation/checking is offline. Database access goes through db:migrate.
export default defineConfig({
  dialect: "postgresql",
  schema: "./src/platform/db/schema.ts",
  out: "./drizzle",
  strict: true,
  verbose: false,
});
