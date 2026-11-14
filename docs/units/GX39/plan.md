# GX-39 plan

Critical path (~35 min): 2 (golden test) -> 3 (split) -> 4 (seams) -> gate. Items 1 and 5 are docs; 2 and 3 share `test_gate_report_skips.py`/`gate_report.py` so they run in sequence (real edge: 3 needs 2's golden to prove identity). No parallel fan-out: the whole unit is ~300 lines in two files, so one writer is faster than coordinating.

1. Audit and plan docs (`docs/units/GX39/audit.md`, `plan.md`).
2. Golden test: identical v3 payload on a fixture, digest taken before the split (`test_gate_report_skips.py`).
3. Split `gate_proof.py`, `gate_adjudicate.py`, `gate_publish.py` and `gate_tier.py` (`current`, `cacheable`, `adjudicated`; both others import it) out of `gate_report.py`; registry reads stay in `gate_report`; literal baseline drops the moved `1000`.
4. Seams: `gate_keys.key_parts()` and `gate_carry.py` stubs; `gate_result_cache.py` calls `gate_tier.cacheable` and `gate_keys.key_parts`.
5. RETRO (`docs/units/GX39/retro.md`).

Premises: GA-P01 (P-42), high (proof is content-addressed; this unit only prepares the seam); seam, low. None is CRITICAL.
Tests: items 3 and 4 run `test_gate_report_skips`, `test_gate_result_cache`, `test_defect_detect`, `test_gate_failures`, `test_pr_ready`, `test_ports_storage`, `test_gate_split`; one final gate-dev from a base-tip checkout (verdict of record) plus the own-checkout run (report-only).
Known base defects expected: the three env tests listed in audit.md (GX-ENV).
