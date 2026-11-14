# ADDR-MAP-SHARED audit

Base: `mod/roadmap-integration` @ `edf15a1d`. Read-only; every number below comes from a command quoted beside it.

## The stop

`#592` (unit `app-course`, lane `app-lane`) added `contract.entry` to `units/app-course/unit.json`. Step 5 of its plan
regenerated `apps/web/tsconfig.paths.json` with `scripts/generate addresses`, as `generate drift` demands. The gate then
refused it:

    FAIL lane undecidable: the change touches units of several lanes: app-course (app-lane), web-build (tooling-lane)

`apps/web/tsconfig.paths.json` is in `units/web-build/unit.json`'s `paths` (13 entries) and was **not** in its `shared`
list, which held only `apps/web/eslint.config.mjs` and `apps/web/tsconfig.json`.

    $ python3 -c "import json;print(json.load(open('units/web-build/unit.json'))['paths'])"
    ['apps/web/design/**', 'apps/web/drizzle.config.ts', 'apps/web/eslint.config.mjs', 'apps/web/next.config.ts',
     'apps/web/package.json', 'apps/web/playwright.config.ts', 'apps/web/playwright.production.config.ts',
     'apps/web/stylelint.config.mjs', 'apps/web/tooling/**', 'apps/web/tsconfig.json', 'apps/web/tsconfig.paths.json',
     'apps/web/vercel.json', 'apps/web/vitest.config.ts']

## Why it cannot stay a lane decision

The file is the OUTPUT of `scripts/generate addresses` (`config/registry/generate.json`, target `addresses`, output
`tsconfig.paths.json`; TX32). The generator writes one `paths` entry per `@ou/<id>` address, and an address exists for
every unit whose `contract.entry` is set. So **any unit that gains a contract rewrites a file that belongs to
web-build**: the lane of that change is undecidable by construction, and the gate refuses a change the generator itself
demanded. The drift rule and the lane rule were in direct contradiction.

Three readers, all inside the repository:

    $ git grep -ln 'tsconfig\.paths' -- scripts apps
    apps/web/scripts/lib/ou-addresses.mjs     (reads the map instead of copying a specifier or a path)
    apps/web/tsconfig.json                    ("extends": "./tsconfig.paths.json")
    apps/web/vitest.config.ts
    scripts/tests/fixtures/architecture/check-architecture.legacy.mjs
    scripts/tests/test_units.py
    scripts/tests/train/test_train_shard.py

None of them is outside the repository, so the durable cure for this datum is the one written in
`backlog/por-que-arquivos-compartilhados.md` (a generated file with a regenerating merge driver), which is CENSO's step
3bis territory. This unit does the smallest true thing now: it declares the file shared, exactly as its two neighbours
already are.

## The rule this applies

`shared` means "several lanes write this legitimately". It is a declaration of fact about the file, not a permission
granted to a lane. `apps/web/tsconfig.json` and `apps/web/eslint.config.mjs` are already declared shared for the same
reason; `apps/web/tsconfig.paths.json` is the third file of the same family and was left out by oversight when
`LANE-OWN` (`56bb626d`, merged as #771) added the two.

## Effect measured before the change

    $ PYTHONPATH=scripts/lib python3 -c "...own.lanes('edf15a1d', ['units/web-build/unit.json','scripts/tests/test_units.py'])"
    lanes {'engine-units': 'engine-lane'}

This unit's own change touches one lane and is decidable either way; the change it repairs (`#592`) is the one that was
refused.

## What this change does not fix

Declaring the file shared makes the LANE decidable. The second half of the same refusal — `pr.refused reason=ownership`
on a shared path, the `refusals()` half — is `SHARED-NEEDS-NO-OWNER`'s (`#778`). Until that lands, a PR that only
regenerates this file is decidable but still waits for `tooling-lane`'s approval. Both halves are needed for `#592` to
travel; neither one alone.
