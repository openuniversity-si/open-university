/**
 * ADR-11 policy shared by the Playwright guard and verify:no-video.
 * Pure module: no Playwright import, so it is unit-tested with Vitest.
 */
export const BLOCKED_VIDEO_DOMAINS = ["mux.com", "litix.io"] as const;

export type NoVideoViolation =
  | { readonly kind: "request"; readonly url: string }
  | { readonly kind: "play-call"; readonly src: string }
  | { readonly kind: "play-event"; readonly src: string };

export interface NoVideoRecord {
  readonly testId: string;
  readonly title: string;
  readonly project: string;
  readonly file: string;
  /** "failed" for the guard self-tests, which are expected to be rejected. */
  readonly expectedStatus: string;
  readonly violations: readonly NoVideoViolation[];
}

export function isBlockedVideoHost(hostname: string): boolean {
  const host = hostname.toLowerCase().replace(/\.$/, "");
  return BLOCKED_VIDEO_DOMAINS.some((domain) => host === domain || host.endsWith(`.${domain}`));
}

export function isBlockedVideoUrl(url: string): boolean {
  try {
    return isBlockedVideoHost(new URL(url).hostname);
  } catch {
    return false;
  }
}

export function describeViolation(violation: NoVideoViolation): string {
  switch (violation.kind) {
    case "request":
      return `request to ${violation.url}`;
    case "play-call":
      return `HTMLMediaElement.play() called (src: ${violation.src || "none"})`;
    case "play-event":
      return `media "play" event fired (src: ${violation.src || "none"})`;
  }
}

/** Installed in every page before any app script runs. */
export const PLAY_INSTRUMENTATION_SCRIPT = `(() => {
  const report = (kind, el) => {
    const src = (el && (el.currentSrc || el.src)) || "";
    const fn = window.__towerNoVideoReport;
    if (typeof fn === "function") fn({ kind, src });
  };
  const proto = HTMLMediaElement.prototype;
  Object.defineProperty(proto, "play", {
    configurable: false,
    writable: false,
    value: function play() {
      report("play-call", this);
      return Promise.reject(new DOMException("Blocked by the no-video guard (ADR-11)", "NotAllowedError"));
    },
  });
  window.addEventListener("play", (event) => report("play-event", event.target), true);
})();`;
