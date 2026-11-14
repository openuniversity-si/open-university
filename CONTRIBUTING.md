# Contributing

Thank you for your interest. This repository takes changes as pull requests on GitHub against `main`.

- **One change per pull request**, with what it does, why, and how it was verified in the description.
- **The gate.** Every pull request is judged by the project's verifier: it runs the tests the diff affects (the map is
  `scripts/tests/covers/*.json`) and publishes its verdict as the `tower/gate` status of the exact commit. A change to
  the gate's own tooling runs the whole script suite. The suite is not run by GitHub Actions.
- **The merge queue.** Pull requests land through GitHub's merge queue: each one is judged again on top of `main` and
  the pull requests ahead of it (`merge_group`). Nobody pushes to `main` directly.
- **Tests first.** A fix carries a test that is red on `main` and green with the fix.
- **No secrets, no internal data.** Never commit credentials, tokens, account identifiers or internal host names; the
  configuration registry (`config/registry/`) holds values, and secrets live in the deployment's secret store.
- **Local checks.** `bash scripts/cloud/setup.sh`, `source scripts/cloud/env.sh`, then `scripts/run test <name>` for a
  script test or `scripts/test-suite` for all of them.

By contributing you agree that your contribution is licensed under the Apache License 2.0 (see `LICENSE`).
