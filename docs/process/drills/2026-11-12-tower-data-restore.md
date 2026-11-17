# Restore drill: tower-data, 12/11/2026

**Source:** the Torre's report in the PADRAO-DEV session, 17/11/2026 17:35 BRT. The drill ran on AWS with the account's
owner credentials, which no session holds; this record keeps what was reported.

- **What was restored:** a point-in-time restore of the RDS instance `tower-data` to 2026-11-12T15:33:40Z, into a
  temporary instance of class `db.t4g.micro`.
- **Time to available:** about 19 minutes.
- **Verification:** `python -m tower_infra restore-check` (`infra/service/tower_infra/restore_check.py`) read the
  restored instance and production; the counts came out identical.
- **Clean-up:** the temporary instance was deleted; a read of it afterwards answered `DBInstanceNotFound`.
- **Next drill:** within `operation.restore_max_days` (90 days) of this one, that is, by 10/02/2027. Past that date the
  data store `DATA-tower-data` turns `unverified` again on its own.
