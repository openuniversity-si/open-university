# TOOLCHAIN-ATTEST-STORE — research

## Quem já resolveu
- Bazel remote cache action keys (https://bazel.build/remote/caching): the key hashes the command, its input files and declared env; undeclared runtime state is excluded, so any worker computes the same key.
- Nix store paths (https://nixos.org/manual/nix/stable/store/store-path): the derivation hash is over its declared inputs only; the same inputs give the same path on any machine.
- Reproducible Builds (https://reproducible-builds.org/docs/): identity is a function of the source, never of the build host's mutable state.
- Buck2 / Pants remote execution: the platform/toolchain is a hashed, committed input, not ambient configuration.

## Estado da arte
Hermetic identity: hash the declared, committed inputs (and the observed installed binaries), never mutable runtime configuration. Requires every input that changes the outcome to be committed or observed.

## Encaixe em nós
Copy (option A). `registry_digest()` hashes the committed registry defaults only; `install_id` (pins, toolchain is a bootstrap owner, already store-independent), the observed binaries and the machine stay. Option B (both read the same store) rejected: the id would still move with every runtime `config set` between gate and train (any `train.*` tweak would void every verdict), and the gate would need forge reads it avoids today.

## Escada de ambição
Now: committed-registry digest (this PR). Next: declare which registry owners are toolchain inputs and hash only those, so an unrelated committed parameter change does not void verdicts. Later: one content-addressed toolchain manifest shared by gate and train (Nix-style).
