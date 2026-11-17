import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import { closeSync, readFileSync } from "node:fs";
import { hostname } from "node:os";
import { createInterface } from "node:readline/promises";
import { fileURLToPath } from "node:url";
import { createYouTubeOEmbed } from "../src/playback/server/oembed-resolver.ts";
import { fetchTransport } from "./lib/catalog-cli/client.ts";
import type { Runner } from "./lib/catalog-cli/context.ts";
import { UsageError } from "./lib/catalog-cli/errors.ts";
import { main } from "./lib/catalog-cli/main.ts";
import { runToCompletion } from "./lib/catalog-cli/drain.ts";
import { parseCredentials, type Credentials } from "./lib/catalog-cli/target.ts";

// tower-catalog's Node half (docs/catalog/cli.md). Run it through tooling/tower-catalog: the wrapper loads
// admin-media.env and writes the secret to file descriptor TOWER_CATALOG_SECRET_FD, never to argv or the environment.
const SECRET_VARIABLES = ["TOWER_ADMIN_MEDIA_SECRET", "TOWER_ADMIN_SECRET_PROD", "TOWER_ADMIN_SECRET_PREVIEW", "TOWER_MEDIA_PREVIEW_BYPASS"];
let credentials: Credentials | null = null;

function readCredentials(): Credentials {
  if (credentials) return credentials;
  const fd = process.env.TOWER_CATALOG_SECRET_FD;
  if (fd === undefined || !/^\d+$/.test(fd)) throw new UsageError("Run tower-catalog through tooling/tower-catalog (or the installed ~/.local/bin/tower-catalog): it loads admin-media.env and passes the secret on a file descriptor.");
  let text: string;
  try { text = readFileSync(Number(fd), "utf8"); closeSync(Number(fd)); } catch { throw new UsageError("Could not read the secret descriptor from the wrapper."); }
  credentials = parseCredentials(text);
  return credentials;
}

/** Children (tower-media, git, gh) get an environment without the secret variables. */
const run: Runner = (command, args, options = {}) => new Promise((resolve) => {
  const env: NodeJS.ProcessEnv = { ...process.env };
  for (const name of [...SECRET_VARIABLES, "TOWER_CATALOG_SECRET_FD"]) Reflect.deleteProperty(env, name);
  const child = spawn(command, args, { cwd: options.cwd, env, stdio: options.inherit === true ? "inherit" : "pipe" });
  let stdout = "";
  let stderr = "";
  child.stdout?.on("data", (chunk: Buffer) => { stdout += chunk.toString(); });
  child.stderr?.on("data", (chunk: Buffer) => { stderr += chunk.toString(); });
  child.on("error", () => { resolve({ code: 127, stdout, stderr: `cannot run ${command}` }); });
  child.on("close", (code) => { resolve({ code: code ?? 1, stdout, stderr }); });
});

const interactive = process.stdin.isTTY && process.stderr.isTTY;
await runToCompletion(() => main(process.argv.slice(2), {
  io: {
    stdout: (text) => { process.stdout.write(text); },
    stderr: (text) => { process.stderr.write(text); },
    prompt: interactive ? async (question) => {
      const readline = createInterface({ input: process.stdin, output: process.stderr });
      try { return await readline.question(question); } finally { readline.close(); }
    } : null,
  },
  env: process.env,
  hostname: hostname(),
  uuid: randomUUID,
  now: () => new Date(),
  sleep: (ms) => new Promise((resolve) => { setTimeout(resolve, ms); }),
  oembed: createYouTubeOEmbed(),
  run,
  appRoot: fileURLToPath(new URL("../", import.meta.url)),
  home: process.env.HOME,
  transport: (target) => fetchTransport(readCredentials(), target),
  secrets: () => (credentials ? [...new Set([credentials.secrets.prod, credentials.secrets.preview])] : []),
}));
