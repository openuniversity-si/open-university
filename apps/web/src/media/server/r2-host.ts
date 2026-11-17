const r2PublicBridge = /^pub-[a-f0-9]{32}\.r2\.dev$/;

/** Dev bridge of the media bucket. Production serves the custom domain instead. */
export function isR2PublicBridge(host: string): boolean {
  return r2PublicBridge.test(host);
}
