# ORIGIN-FINISH — research

## Quem já resolveu
- Forge migrations with a single selector: Gitea/Forgejo "mirror then flip" migrations (pull mirror kept until the
  cut-over, then the mirror is made the primary and push access moves) — the standard sequence for moving a repository's
  home between forges.
- GitLab's "import from GitHub" plus repository mirroring (push/pull mirrors): the cut-over is a settings change, the
  CI and merge tooling follow the selected remote.
- Hexagonal ports and adapters (Cockburn): the operation talks to a port; swapping the adapter is configuration, and a
  readiness check of the adapter is what makes the swap safe.
- Feature-flag cut-overs with a preflight (Kubernetes readiness probes, Terraform plan before apply): the switch is
  refused, or at least named, while a precondition is unmet.

## Estado da arte
- Standard: mirror the repository on the new forge, freeze writes on the old one, flip the remote and the CI/merge
  integration in one step, keep the old forge read-only for a window.
- Most advanced: the delivery engine owns the forge choice as data (one key), checks the selected adapter's
  credentials and reach before any run, and refuses to start rather than fall back.

## Encaixe em nós
- Copy directly: the single selector (`forge-events.adapter`, D-283) already exists; the change store makes the flip a
  reversible, recorded operator step (`scripts/config set` / `revert`).
- Adapt: the preflight checks credentials per provider with GitHub hard-wired; it must check the forge the selector
  names, so the flip is safe to apply and its gaps are named before a run.
- Does not fit: a pull mirror that keeps GitHub writable (a dual path the brief forbids); a fallback to GitHub on an
  Origin failure (forbidden).

## Escada de ambição
- Minimum useful step now: remove the GitHub calls the repository still makes outside the adapters that are dead or
  forge-agnostic, make the preflight check the selected forge, and write the exact outside steps of the cut-over.
- Next: the coordinator mirrors the repository on Origin, gives the VM and the cloud environments the Origin CLI, key and
  egress, and sets `forge-events.adapter=origin` in the change store.
- State of the art: the first PR flows on Origin end to end; GitHub's adapter stays registered and unselected; the
  remaining GitHub artefacts (the `gh` toolchain pin, the GitHub-only registry keys) leave with the next units.
