import { AppError } from "../../kernel/errors.ts";
import { currentEnv, type EnvInput } from "../../kernel/env.ts";

/** Storage access. R2 is the one media store. A passed map is the fixture; an omitted map is the kernel facade. */
export function getMediaStorageEnv(input?: EnvInput): Readonly<{ access: "ro" | "rw" }> {
  const env = input ?? currentEnv();
  const access = env.MEDIA_ACCESS === "ro" ? "ro" : "rw";
  if (access === "rw" && !(env.R2_ACCESS_KEY_ID_RW && env.R2_SECRET_ACCESS_KEY_RW)) throw new AppError("unconfigured", "R2_ACCESS_KEY_ID_RW is required.");
  if (access === "ro" && !((env.R2_ACCESS_KEY_ID_RO && env.R2_SECRET_ACCESS_KEY_RO) || (env.R2_ACCESS_KEY_ID_RW && env.R2_SECRET_ACCESS_KEY_RW))) {
    throw new AppError("unconfigured", "R2_ACCESS_KEY_ID_RO is required.");
  }
  return { access };
}
