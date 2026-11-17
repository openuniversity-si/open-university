import { EXIT } from "./errors.ts";

/**
 * Runs the CLI's main and guarantees a visible, non-zero exit if Node drains the event loop while it is still pending
 * (a request nothing keeps alive would otherwise end the process with exit 13 and no message).
 */
export async function runToCompletion(main: () => Promise<number>, io: { readonly stderr: (text: string) => void } = { stderr: (text) => { process.stderr.write(text); } }): Promise<void> {
  let settled = false;
  const drained = () => {
    if (settled) return;
    io.stderr("tower-catalog: the process stopped with a request still pending and no answer; nothing was confirmed. Re-run the same command.\n");
    process.exitCode = EXIT.network;
  };
  process.once("exit", drained);
  try {
    process.exitCode = await main();
  } finally {
    settled = true;
    process.removeListener("exit", drained);
  }
}
