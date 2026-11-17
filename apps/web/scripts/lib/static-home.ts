/** ADR-16 guardian over `<distDir>/prerender-manifest.json`: the visitor Home is ISR, the signed-in Home never is. */
export const HOME_MAX_REVALIDATE_SECONDS = 300;

interface PrerenderManifest { readonly routes?: Readonly<Record<string, { readonly initialRevalidateSeconds?: number | false }>> }

export function staticHomeFailures(manifest: PrerenderManifest, signedInPath: string): string[] {
  const routes = manifest.routes ?? {};
  const failures: string[] = [];
  const home = routes["/"];
  if (!home) failures.push("/ is not prerendered (dynamic): it must stay static for visitors.");
  else if (typeof home.initialRevalidateSeconds !== "number" || home.initialRevalidateSeconds <= 0 || home.initialRevalidateSeconds > HOME_MAX_REVALIDATE_SECONDS) {
    failures.push(`/ must revalidate within ${String(HOME_MAX_REVALIDATE_SECONDS)} s.`);
  }
  if (signedInPath in routes) failures.push(`${signedInPath} is prerendered: per-viewer HTML must never be cached.`);
  return failures;
}
