# TRAIN-RESYNC-TOOLCHAIN — intake

## Pedido
Daniel (CEO), 2026-10-29, launch prompt of this session, literal: "Bug seen 29/10 16:27 BRT on PR #805: when
admission refuses a verdict because it came from a different toolchain (not because the base moved), the train's
D-075 resync (train_verdict.hand_back / requeue path) does not produce a new head sha, so it emits pr.conflicted with
no files and hands the PR back to its owner, which is a false conflict. The workaround was to switch
train.verdict_fallback to tier2. [...] Fix: the train must re-verdict the same head itself (cold verdict with the
current pinned toolchain) when the refusal reason is toolchain/pin mismatch; never emit pr.conflicted without real
conflicting files (add a guard + test). After the fix, restore train.verdict_fallback=requeue through scripts/config
set --reason, only once merged (say so in the PR; the train-role session or follow-up does it). Record a D-NNN if it
amends D-075. Comment a short pt-BR summary on the PR."

## Intenção
The train, not the owner session, finishes every PR that is ready (D-075, Daniel 15:02: updating the base is the
train's work). A refusal that only says "this verdict came from another machine" is the train's own business: the
owner did nothing wrong and must not be interrupted. And `pr.conflicted` must keep one meaning, so an owner session
that receives it can trust that there is a file to resolve.

## Contexto
- #802 (TRAIN-VERDICT) added verdict admission and the requeue resync; #805 (TRAIN-VERDICT-FIX, merged 20:15Z) is on
  the base. Its item 8 already reacted to the 19:27Z event: a head that contains the tip gets a resync merge commit
  with the head's tree (a new sha, so a new `pr.ready`), and `pr.conflicted` v2 carries `cause` (`textual` with
  files; `not-admitted`, `unpushable`, `forge-refused` with none).
- So today the false conflict of 19:27Z is no longer emitted for that exact path, but: (a) the train pushes a merge
  commit that changes nothing into the owner's branch only to get a new sha; (b) `pr.conflicted` with `files: []` is
  still a legal, emitted event for three causes, and the owner session still gets it.
- `train.verdict_fallback` is `tier2` in the store since 19:31Z (D-072 evaluation, #548/#805 comments).
- Production is frozen (D-054); the train merges into `mod/roadmap-integration` only.

## Regras
- D-075 (verdict admission, requeue resync by the train), amended by this unit → a new D-NNN entry.
- D-072 (blocking events are evaluated, not waited on), D-054 (no production change), D-065 (events, never a clock),
  D-025 (commit discipline), D-077 (this unit flow), D-055 (no review step).
- Premises P-53 (no-ff merge of a head containing T has tree(head)), P-43 (no tier-1 box-local markers in an admitted
  verdict), P-46 (the pinned gate).
- Config changes only through `scripts/config set --reason`; never on this PR's branch before it merges.

## Problema real
A verdict refused for a reason that is not the base (toolchain, gate version, warmth) on a head that already contains
the tip ends either in a false `pr.conflicted` or in a redundant push to the owner's branch, instead of the train
re-verdicting that same head and merging it. Resolved when: a test reproduces #805 (head contains the tip, verdict
from another toolchain) and the train merges the unchanged sha after its own cold verdict, pushing nothing; and no
code path can emit `pr.conflicted` with an empty `files` (a guard that raises, with a test).

## Lacunas
- Whether a forge refusal or an unpushable branch should still reach the owner: decided in the audit (they are not
  textual conflicts; the train keeps the PR or halts, D-072 evaluation, no question to Daniel).
- When the train-role session restores `train.verdict_fallback=requeue`: after this merges, outside this PR.
