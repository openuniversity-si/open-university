# PB1 audit

- `premises.check_line` (called by `structure-check --pr-body`) counted any `confirmed` premise as settled; it never looked at `answer.quote`.
- `record_errors` accepts `answer.quote or answer.where` for confirmed, so a link alone confirms. `scripts/premises answer` inherits that.
- Unconfirmed premises are already handled by radius: `premises.blocking_radii` (high) fails, `premises.warning_radii` (medium) warns, low is counted.
- Register evidence: 14 confirmed premises (P-27..P-40) have a `where` link and no quote; P-03/P-08/P-26 are `validated` by measurement.
- Nothing duplicates this elsewhere (commit_check, config_check, hermetic_check do not read premises).
