// pnpm hook: drizzle-orm declares an optional peer for every database driver it supports. Keep only the peers this
// app installs itself (pg and @types/pg), so the lockfile records the one PostgreSQL driver the app uses.
const app = require("./package.json");

const direct = new Set([...Object.keys(app.dependencies ?? {}), ...Object.keys(app.devDependencies ?? {})]);
const keep = (map) => (map ? Object.fromEntries(Object.entries(map).filter(([name]) => direct.has(name))) : map);

module.exports = {
  hooks: {
    readPackage(pkg) {
      if (pkg.name !== "drizzle-orm") return pkg;
      pkg.peerDependencies = keep(pkg.peerDependencies);
      pkg.peerDependenciesMeta = keep(pkg.peerDependenciesMeta);
      return pkg;
    },
  },
};
