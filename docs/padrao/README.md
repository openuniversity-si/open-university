# Padrão

The Padrão is the way of doing, versioned: Padrão → Motor (the Padrão installed here) → Execução (commit, PR, program, release). Executions produce lessons (`scripts/lessons`); a lesson marked `padrao_candidate` proposes a change here.

`v1/padrao.json` lists the rule files in the order the launch brief carries them (`scripts/lib/coordinator_launch.py`). The active version is `coordinator.padrao_version`. A new version is a new folder (`v2/`); a published version is never edited in place.

Since v6 (D-077) the unit flow is INTAKE → RESEARCH → AUDIT → PLAN → execution → RETRO (`v6/intake-and-research.md`); the `structure check` enforces the two new files on units and programs created after the rule.

Since v7 (D-081) the audit follows each finding down a chain of whys to a classified structural root (`## Causas raiz`) and the plan weighs 2–4 alternatives per structural root before its `## Escolha` (`v7/audit-and-plan.md`, templates `docs/process/templates/audit.md` and `plan.md`); the `structure check` enforces both on units and programs created after `intake.root_cause_since`.

Since v8 (D-115) a program (`docs/programs/<program>/`, a set of PRs that brings a solution to the ideal) runs avaliação → pesquisa → diagnóstico → solução → phases → retro (`v8/program.md`, templates in `docs/programs/_template/`): first principles and the ideal system, how the best do it, a measured baseline with one main metric and guard metrics, a 10x ladder of phases with targets and stop criteria, and a phase that passes only when the main metric reaches its target and no guard gets worse. Units and ad hoc tasks keep v7's flow. v8 is the first version `coordinator.padrao_version` names since v1.

The management method above the versions is [METODO.md](METODO.md) (Daniel 2026-11-02): programa, projeto, processo and operação, each with its own closing proof; PDCA for programa and projeto, SDCA for processo and operação. It supersedes the MGMT-METHOD plan (Origin PR #3, the old #1066), whose research stays as reference. Where it conflicts with v7/v8, the method prevails until the structure check is aligned.
