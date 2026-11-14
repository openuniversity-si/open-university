# OU-DECOUPLE — research

Unit, stage 2 of Daniel's unit standard of 30/10 (Pesquisa, with sources). It looks outward from the intake's real
problem: how teams draw the line between a platform and its products, extract a product with its history, archive it
and retire its production. Complete on its own; it raises no questions for the diagnosis.

## Quem já resolveu
1. **git filter-repo** ([man page](https://www.mankier.com/1/git-filter-repo); recommended by GitHub's
   [Splitting a subfolder out into a new repository](https://docs.github.com/en/get-started/using-git/splitting-a-subfolder-out-into-a-new-repository)).
   `--subdirectory-filter <dir>` (or `--path <dir>/`) rewrites a fresh clone so it holds only that directory's
   history. Branches and tags of the original are not carried, and the tool removes the remote so nothing is pushed
   by accident.
2. **git subtree split** ([git-subtree](https://manpages.debian.org/testing/git-man/git-subtree.1.en.html)). Builds a
   synthetic history of a prefix (only the commits that touched it, the prefix at the root), into a branch ready to
   push. It ships with git and needs no install, but it is slower on long histories.
3. **Google's monorepo** ([Potvin and Levenberg, CACM 2016](https://research.google/pubs/why-google-stores-billions-of-lines-of-code-in-a-single-repository/))
   and **Bazel visibility** ([concepts/visibility](https://bazel.build/concepts/visibility)). Products share one
   repository, but a target is private by default. A dependency on a target that is not visible fails at analysis.
   Every file belongs to exactly one package, the one of its nearest `BUILD` file, so no file is unowned.
4. **Nx module boundaries** ([enforce-module-boundaries](https://nx.dev/docs/features/enforce-module-boundaries.md))
   and **Shopify Packwerk** ([enforce_dependencies](https://github.com/Shopify/packwerk/discussions/260)). Projects
   carry tags or a `package.yml`, and a lint or `packwerk check` fails a forbidden import. Packwerk's `strict` mode
   refuses new violations while a todo file lists the old ones, so a boundary can be adopted step by step.
5. **Retiring what is left**. [GitHub archiving](https://docs.github.com/en/repositories/archiving-a-github-repository/archiving-repositories)
   makes a repository read-only and is reversible. Vercel's [Pause a project](https://vercel.com/docs/rest-api/projects/pause-a-project)
   (`POST /v1/projects/{projectId}/pause?teamId=…`, undone by `/unpause`) stops serving production: visitors get
   [503 `DEPLOYMENT_PAUSED`](https://vercel.com/docs/errors/DEPLOYMENT_PAUSED), and service returns within minutes
   of an unpause with no redeploy. Deployments, domains, environment variables and the attached stores stay as they
   are.

## Estado da arte
- **Standard.** Boundaries are declared and checked by the build (visibility, tags, packages). A product leaves a
  shared repository in three moves: tag the last commit that holds it, extract it with filter-repo into its own
  repository if it will live again, then delete the directory in one change. Its service is retired by stopping
  traffic in a reversible way while the data is kept.
- **Most advanced.** Ownership is total by construction (every file in a package, enforced at analysis). The affected
  set of a change is computed from the dependency graph (Bazel `rdeps`), so a change runs only what depends on it.
  Products consume the platform through versioned interfaces and never the other way round. It costs a build system
  that knows every edge, which GATE-SPEED's wave 4 (Bazel on the e2-micro) is still to measure.

## Encaixe em nós
| Idea | Fit | Why |
|---|---|---|
| Tag the last commit that holds OU, push it, record the sha | copy | One ref keeps every byte and the whole history, costs nothing and is free. A later archive repository can be cut from it at any time. |
| filter-repo into a private archive repository now | does not fit now | The tag already loses nothing. This session cannot create a repository (GitHub scope is `openuniversity-si/open-university`), and the command is recorded so Daniel can run it from the tag when he wants a standalone OU. |
| Delete the product directory in one change, after the gate stops depending on it | copy | Order matters because the gate is pinned to the base (P-46, D-096). The base must already run without OU before a PR deletes it. |
| Bazel's "every file in one package" | adapt | We keep our area map, but a check makes it total: an unassigned path fails the gate by name instead of selecting the full battery. |
| Nx/Packwerk "the platform never imports a product" | adapt | A check that no acting engine file names a product path, guarding the 0 this unit reaches. A small literal check, not a new tool. |
| Packwerk's todo list for existing violations | does not fit | We remove every violation in this unit, so no allow-list is kept. |
| Vercel pause | copy | It is the least destructive action that takes the site offline: reversible, no redeploy, nothing deleted, Neon and R2 untouched. |
| Adopt Bazel or Nx now | does not fit | It is a migration of the whole gate, measured separately (GATE-SPEED wave 4), and is not needed to separate one product. |

## Escada de ambição
1. **Minimum useful step (the plan's cheapest useful effort):** every path gets an area and a check holds it; the
   engine's diffs stop selecting OU stages; the tag is pushed; OU is deleted; the engine's references become generic or
   go; the site is paused last.
2. **Next:** a declared product seam. A product registers its paths, stages and units in one manifest, and the engine
   reads only that, so the next product is added and retired without touching engine code. The guard check is its
   first enforcement.
3. **State of the art:** ownership and affected sets computed from a build graph (Bazel-like), with visibility
   enforced at analysis, once wave 4 shows the e2-micro can carry it.
