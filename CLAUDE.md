@AGENTS.md

On `continue` or `continue (docs/RETOMAR.md)`, follow [docs/RETOMAR.md](docs/RETOMAR.md) as step 0, then resume
SEMENTE §8 step 3 with the current Origin state and active claims.

Follow AGENTS.md for the canonical delivery flow. This repository is the engine of A Torre; Open University is archived at `567176bb` (D-110). Production (Open University's site) is frozen (D-054, `docs/process/RELEASES.md`) until Daniel pauses it.

## Claude Code cloud

Set `CURSOR_API_KEY` as an environment secret; the `origin` CLI uses it to reach the repository on Cursor Origin. GitHub (`openuniversity-si/open-university`) is archived and needs no credential.

`bash scripts/cloud/setup.sh` runs from the SessionStart hook and installs the pinned toolchain in `.toolchain/`, including PostgreSQL 18.6 on `127.0.0.1:54322` without Docker or root (versions in `config/registry/toolchain.json`, checksums in `scripts/cloud/toolchain.json`). It does not use `apt-get` or `sudo`.

`scripts/cloud/preflight` prints every missing toolchain tool, credential, Origin forge gap, test-database gap, host tool or writable path and exits 2. It does not print secret values.
