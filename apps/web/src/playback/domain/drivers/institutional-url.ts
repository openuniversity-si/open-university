import { invalid } from "../../../kernel/errors.ts";
import type { SourceDriver } from "../../ports/source-driver.ts";

const empty = { scriptSrc: [], frameSrc: [], mediaSrc: [], imgSrc: [], connectSrc: [] } as const;

/** External HTTPS link on an explicit host allowlist. It does not embed and it does not widen CSP. */
export function institutionalUrlDriver(allowlist: readonly string[]): SourceDriver {
  const hosts = new Set(allowlist.map((host) => host.toLowerCase()));
  return {
    provider: "institutional-url",
    cspDomains: empty,
    validateSource(input) {
      if (input.provider !== "institutional-url") return ["provider"];
      let url: URL;
      try { url = new URL(input.url); } catch { return ["url"]; }
      if (url.protocol !== "https:" || url.username || url.password || url.hostname === "") return ["url"];
      if (!hosts.has(url.hostname.toLowerCase())) return ["url"];
      return [];
    },
    toPlaybackDescriptor(input) {
      if (input.provider !== "institutional-url" || this.validateSource(input).length > 0) throw invalid("Invalid institutional URL.");
      return { kind: "external-link", url: input.url };
    },
  };
}
