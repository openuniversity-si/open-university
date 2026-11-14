# BODY-GATE — audit

## What was measured, and when

28/10/2026, between 16:20 and 16:45, against `mod/roadmap-integration` at `5a753035`.

The train reported an empty queue while 20 pull requests were open and out of draft. Reading the queue
itself was the first answer: 19 of the 20 had no `pr.ready` at all, and the twentieth (#615) had one for a head
that its branch has since moved past, so it left the queue by rule.

Running `scripts/train queue` in the integration checkout printed nothing and exited 0. A queue read that
succeeds and returns nothing is not a broken read — it is a true reading of a queue nobody announced into.

## Why the announcements are missing

`pr.ready` is emitted by `scripts/pr-ready`, and an entry reaches the queue only when its gate passed on the
exact head it names. So every one of those 20 PRs died before the last step, at the gate.

The gate was run on #663 after merging the current base into it. Nineteen stages passed and one failed:

    pr.checked: published #663 fail sha=b0adcb8c base=5a753035
    FAIL effort: the PR body has no `## Cheapest useful effort` block; add it with `Action:`, `Cost:`,
    `Requirement:`, `Cheaper rejected:` for its most expensive action (docs/padrao/v4/effort.md)

Of the twenty open PRs, twenty lack that block. The rule landed today at 15:43 (`38e15b05`), and every one of
those bodies was written before it existed.

## The shape of the defect

This is the same defect that stopped the batch earlier today, in the other place the block lives. `#770`
(EFFORT-STEP) landed a rule that judged every plan in the tree, so a PR went red for the plans of two other PRs
written before the rule; the fix was to judge a plan by the date it was created. The rule has two homes — the
unit's plan and the PR body — and only one of them learned the date lesson.

A rule that judges work written before it exists does not raise quality. It stops the flow, and a stopped flow
is the failure the whole engine is built to prevent.

## What is granted by the fix, and what is not

A PR opened before the rule lands is not judged by it, exactly as a plan written before the rule is not. A PR
opened after it is judged. An old PR that does carry the block is judged by it — the exemption is for having no
block, not for being old, so a malformed block on an old PR is still red. Without a birth date, or in a checkout
that does not carry the registry, the body is judged: the exemption only ever applies to something the checkout
can prove.

## Evidence that the fix bites

- `scripts/tests/test_structure_effort.py`: 33 tests green, six of them new for this body path.
- Mutation 1 — disabling the exemption: `test_a_pr_opened_before_the_rule_is_not_judged_by_it` fails, alone.
- Mutation 2 — letting the exemption cover an old PR that has a block: `test_an_old_pr_that_carries_a_block_is_judged_by_it` fails, alone.
- `scripts/tests/test_structure.py`: 66 tests green. `scripts/tests/test_commit_check.py`: 20 tests green.
