# GX-00 audit (read-only, cheap evidence)

| Area | Evidence | Consequence |
|---|---|---|
| Base | `origin/mod/roadmap-integration` = 2e423b7e at start; `mod/gx00` did not exist on the remote. | Branch created from the base tip. |
| Sources | `origin/mod/ga3` 70a5f444 holds `docs/programs/gate-excellence/plan.md` only; `origin/mod/ga1` bed976b1 holds `audit-1-fable.md`, `origin/mod/ga2` 6c842b2d holds `audit-2-opus.md`; each branch differs from the base by that one file. | Copy the three files verbatim, one commit each for the audits. |
| Program folder | `docs/programs/_template/` has audit, brief, plan, retro; `scripts/program check` needs all four files. Base has no `gate-excellence/` folder. | Add `brief.md`, `audit.md` (index), `retro.md` (template). |
| Premises | Register holds P-01 … P-41 (`docs/process/premises/*.yml`); ids are assigned by `scripts/premises propose`. | Citing audit ids (GA-P02) would resolve the wrong premise; record the six with real ids. |
| Decisions | `docs/domain/DECISIONS.md` ends at D-069; one table row per decision. | D-070 is the next row (one entry, P-11). |
| Gate-change rule | `commit_check.gate_errors` requires an approved D-NNN in the body of a gate-touching PR. | D-070 is the D-NNN every GX PR cites. |
| Tests | `scripts/tests/{units,premises,program}.test.sh` read these docs (G-15). | Run them before the final gate. |
| Proving tests | `test_gate_pin.py`, `test_gate_result_cache.py` do not exist yet; `test_commit_check.py` exists. | D-070 names them; "test pending" where absent. |
