# TRAIN-ADMIT-GATE-CHANGE — intake

Emergency unit (Daniel, CEO, 29/10/2026 17:47 BRT through A Torre, pt-BR, literal: "Chefia, precisamos acelerar isso
aí. Não podemos ficar parados assim"), approving a new decision (D-079) for what follows.

## Pedido
A PR that changes the gate/train toolchain can never be admitted by verdict. #804 (GATE-FAST, head a415b7d5) was
re-verdicted at 17:38 BRT, PASSED, and was still refused: `pr.conflicted` cause `not-admitted`, "toolchain
710c5639… is not the attested f061b4e0…". The pinned gate on the base PASSED and the head's own gate tooling PASSED
(gate-status advisory, 20:37Z). Fix: admit a toolchain-changing PR on a dual verdict (pinned-on-base PASSED + the
head's own toolchain PASSED, same head, merged tree as P-53 requires); after merge the new toolchain is the pin.

## Intenção
Self-hosting, as Bazel/TAP and Uber SubmitQueue do: infra changes are judged by the old and the new infra; both green
admits. Nobody merges by hand, the train stays the merger.

## Contexto
#802/#805 added verdict admission (D-075); #807 (D-078) re-verdicts the same head on a toolchain refusal. The store
holds `train.verdict_fallback=tier2` since 19:31Z. Production is frozen (D-054); the train merges only into
`mod/roadmap-integration`.

## Regras
The train stays the only merger (D-065 V3); P-53 (tested tree is the merged tree), P-43 (cold, no box-local markers),
P-46 (the pinned gate judges). Never a merge by hand, never the train on the box.

## Problema real
The strict rule compares an attestation that includes what the PR changes; for a toolchain change the comparison is
structurally false, so the PR loops `not-admitted` forever.

## Lacunas
The head-tooling verdict is only an advisory comment today: no verified event. The train runs that leg itself.

