/** Facts the deployment fills. Callers pass the kernel environment map; this file does not read `process.env`. */

type Env = Readonly<Record<string, string | undefined>>;

/** `SITE_ENV`: which deployment this is. Only the exact value `production` is the production deployment. */
export type SiteEnv = "production" | "preview" | "development";

/** The deployment label, or undefined when `SITE_ENV` is unset or not one of the three labels. */
export function siteEnv(env: Env): SiteEnv | undefined {
  const value = env.SITE_ENV;
  return value === "production" || value === "preview" || value === "development" ? value : undefined;
}

/** `production` is the production deployment. `siteIndexable` is the local opt-in, unchanged. */
export function indexingFacts(env: Env): { readonly production: boolean; readonly siteIndexable?: string } {
  return { production: siteEnv(env) === "production", siteIndexable: env.SITE_INDEXABLE };
}

/** Admin acts in production only on the production deployment. Anything else, including unset, is preview. */
export function adminDeployment(env: Env): "prod" | "preview" {
  return siteEnv(env) === "production" ? "prod" : "preview";
}

/** Commit the build published (`BUILD_SHA`, else the forge's `GITHUB_SHA`). Empty when neither is set. */
export function hostCommit(env: Env): string | undefined {
  const sha = (env.BUILD_SHA ?? env.GITHUB_SHA ?? "").trim();
  return sha.length > 0 ? sha : undefined;
}

/** Environment map whose build commit is the published commit when the process did not inline one. */
export function buildEnvFromHost(env: Env): Env {
  if (env.TOWER_BUILD_COMMIT?.trim()) return env;
  const sha = hostCommit(env);
  if (!sha) return env;
  return { ...env, TOWER_BUILD_COMMIT: sha };
}
