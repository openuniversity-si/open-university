import { readFile } from "node:fs/promises";
import { runFactory } from "./lib/factory-cli.ts";

// Node half of scripts/tower-factory. The wrapper selects the pinned Node. ingest reads YOUTUBE_API_KEY here and nowhere else.
const code = await runFactory(process.argv.slice(2), {
  stdout: (text) => { process.stdout.write(text); },
  stderr: (text) => { process.stderr.write(text); },
  readFile: (path) => readFile(path, "utf8"),
}, { env: process.env, fetch: globalThis.fetch, now: () => new Date() });
process.exit(code);
