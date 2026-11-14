# GX-FIX-forge-rate-2 — status

- 2026-10-27 23:06:02Z: POST /repos/openuniversity-si/open-university/pulls refused with HTTP 403. Body: "You have exceeded a secondary rate limit and have been temporarily blocked from content creation. Please retry your request again later." (request id C020:300A8D:37A9429:B784E8E:6AE12E57). This is the known condition. Work continues on the branch, and the PR is retried at most once per ~10 min (next ≥ 23:16Z).
- 2026-10-27 23:08:40Z: one early retry of POST /pulls (2.5 min after the first refusal, against my own ~10 min rule) was refused the same way (request id 2070:22A128:369ABA0:B33BAB9:6AE12EF7). Next retry ≥ 23:19Z.
- 2026-10-27 23:19:29Z: POST /pulls passed: PR #720 (draft). STATUS comment posted. Final gate started at 23:19Z.
