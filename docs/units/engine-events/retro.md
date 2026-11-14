# engine-events — retro

The migration removes both catalog exceptions and keeps provider shapes inside
adapters. Reusing change_files avoided creating an unnecessary operation. The
new historical read has one shared behavioral oracle, inclusive instant bounds,
explicit unsupported-adapter refusals and no capability filter in the adapters.

Baseline comparison required controlling the hermetic judge: the live exception
regime converts two existing structural errors to warnings. Running both trees
with the same bootstrap reproduced exactly the same findings. The consumer test
initially used the production repository name against an o/r transport fixture;
the final fixture binds the consumer repository explicitly. Final suites pass.

Origin's documented mergedSince behavior is exercised by the transport fake;
live server enforcement remains unmeasured. Operation responsibility remains
unknown, without changing responsibility.accepted. No production change or
manual merge was performed.
