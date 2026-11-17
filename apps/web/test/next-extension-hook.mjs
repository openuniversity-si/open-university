// Node 22 resolves an extensionless import only when the package declares it.
// next@16 ships next/cache.js and no "exports" map, so `import "next/cache"`
// dies before the catalog command can answer. Append .js only after that lookup fails.
export async function resolve(specifier, context, nextResolve) {
  if (!/^next\/[A-Za-z0-9-]+$/.test(specifier)) return nextResolve(specifier, context);
  try {
    return await nextResolve(specifier, context);
  } catch (error) {
    if (error instanceof Error && "code" in error && error.code === "ERR_MODULE_NOT_FOUND") {
      return nextResolve(`${specifier}.js`, context);
    }
    throw error;
  }
}
