import type { RequestContext } from "./context.ts";
export type LogLevel = "info" | "warn" | "error";
export type LogField = string | number | boolean | null;
/** Event and correlation are reserved; only primitive fields can cross this boundary. */
export function logStructured(level: LogLevel, event: Uppercase<string>, fields: Readonly<Record<string, LogField>> = {}, context?: Pick<RequestContext, "requestId">): void {
  const safe = Object.fromEntries(Object.entries(fields).filter(([key, value]) =>
    key !== "event" && key !== "requestId" && (value === null || ["string", "number", "boolean"].includes(typeof value))));
  const line = JSON.stringify({ event, ...(context ? { requestId: context.requestId } : {}), ...safe });
  if (level === "info") console.log(line);
  else if (level === "warn") console.warn(line);
  else console.error(line);
}
