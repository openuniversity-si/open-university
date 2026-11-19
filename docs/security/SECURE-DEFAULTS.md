# Secure-defaults baseline

What the AWS stacks (`infra/aws/`) and the site (`apps/web`) set to secure values by default, so that nothing has to
be switched on after a deploy (SSDF PW.9, `config/security/controls/CTRL-ssdf-pw.9.json`). Each item points at the
line that sets it and the test that fails if it is removed. A test named `File::Class::test` runs in the script suite
(`scripts/tests/infra-aws.test.sh` for `test_infra_aws.py`) or in the site's integration suite (`CHK-web`). Line
numbers are those of the commit that adds this file; the test, not the line, is the proof.

This file records the baseline; it changes no setting. A new stack or a new site setting that weakens an item here
breaks the test named next to it.

## Storage: private, owner-enforced, encrypted, TLS only

| Item | Set by | Proved by |
| --- | --- | --- |
| The media bucket blocks every public ACL and policy (all four flags) and enforces the owner on objects | `infra/aws/stacks/60-media.json:95-104` | `test_infra_aws.py::MediaStackTests::test_the_bucket_is_private_versioned_encrypted_and_kept` |
| The media bucket is encrypted at rest (SSE-S3, AES256) | `60-media.json:108-112` | same test |
| The media bucket refuses any request not over TLS (`aws:SecureTransport` false is denied) and only the CDN reads it (origin access control) | `60-media.json:186`, `60-media.json:438-446` | `MediaStackTests::test_only_the_distribution_reads_the_bucket_and_only_over_tls` |
| The media's access-log bucket is private, encrypted and TLS only | `60-media.json:291-308`, `60-media.json:403` | `MediaStackTests::test_the_bucket_is_private_versioned_encrypted_and_kept` |
| The media replica bucket is private, encrypted and TLS only | `infra/aws/stacks/58-media-replica.json:16-33`, `58-media-replica.json:85` | `MediaReplicaStackTests::test_the_bucket_is_private_versioned_encrypted_kept_and_drops_old_versions_at_90_days` |
| The mail bucket is private, encrypted and TLS only | `infra/aws/stacks/65-mail.json:143`, `65-mail.json:160`, `65-mail.json:210` | `MailStackTests::test_the_bucket_is_private_encrypted_written_only_by_this_rule_set_and_emptied_after_30_days` |
| The runner's outputs bucket (stopped) is private, encrypted and TLS only | `infra/aws/stacks/50-runner.json:54-71`, `50-runner.json:125` | `test_infra_runner.py::RunnerStackTests::test_the_bucket_is_private_encrypted_reached_over_tls_and_forgets_the_logs` |

## Database: private, encrypted, IAM authentication, kept

| Item | Set by | Proved by |
| --- | --- | --- |
| tower-data is not publicly accessible and is reached only from the tasks' security group | `infra/aws/stacks/20-data.json:156` | `DataStackTests::test_it_is_private_and_reached_only_from_the_tasks` |
| Storage is encrypted at rest | `20-data.json:137` | `DataStackTests::test_it_keeps_its_data` |
| IAM database authentication is on; the owner's password is an SSM SecureString read by reference | `20-data.json:144` | `DataStackTests::test_it_is_private_and_reached_only_from_the_tasks` |
| Deletion protection is on and a replacement keeps a snapshot | `20-data.json:160` | `DataStackTests::test_it_keeps_its_data` |

## Network: no inbound, HTTPS out

| Item | Set by | Proved by |
| --- | --- | --- |
| No security group takes inbound traffic except the database from the tasks; the tasks go out on HTTPS only; the database opens no connection | `infra/aws/stacks/10-network.json:278-292` | `StackTests::test_the_network_has_no_nat_and_a_private_database` |
| The media CDN serves viewers over HTTPS only, with TLS 1.2 (2021 policy) minimum over SNI | `60-media.json:511`, `60-media.json:540` | `MediaStackTests::test_the_distribution_is_https_only_cached_as_immutable_and_has_nothing_that_bills`, `MediaStackTests::test_a_certificate_and_an_alias_give_the_alias_over_sni` |

## Identity: a boundary on every role

| Item | Set by | Proved by |
| --- | --- | --- |
| Every role the stacks create carries the `tower-boundary` permissions boundary, and the factory may create only `tower-app-*` roles that carry it | `infra/aws/bootstrap.json:45`, `bootstrap.json:157-175` | `BootstrapTests::test_every_role_carries_the_boundary`, `StackTests::test_every_resource_is_a_service_the_boundary_allows` |
| The boundary denies creating users and access keys, budgets, costly compute (instances, NAT) and changing a role's boundary | `bootstrap.json:45` | `BootstrapTests::test_the_boundary_denies_users_keys_budgets_and_the_costly` |

## The site

| Item | Set by | Proved by |
| --- | --- | --- |
| Session cookies are `HttpOnly`, `SameSite=Lax`, and `Secure` whenever the base URL is HTTPS | `apps/web/src/identity/server/config.ts:98-99` | `apps/web/test/int/auth.int.test.ts` (the session cache cookie is `HttpOnly`) |
| The CSRF and origin checks of the auth library stay on; sign-in and every auth route are rate-limited | `config.ts:100-101`, `config.ts:93-94` | `auth.int.test.ts` (cross-origin sign-out refused, the same rate-limit bucket across instances) |
| The admin catalog routes answer 401 without the right Bearer and 429 over the limit | `apps/web/src/app/api/admin/` | `apps/web/test/int/catalog-admin-routes.int.test.ts`, `admin-rate-limit.int.test.ts` |
| The `X-Powered-By` header is off | `apps/web/next.config.ts:41` | none (a setting of Next.js) |

## Gaps (not secure by default yet)

1. **The content security policy allows `'unsafe-inline'` scripts.** Since 19/11 the site enforces its policy
   (`Content-Security-Policy`, `apps/web/next.config.ts`, `apps/web/src/platform/security/csp.ts`) after seven days of
   reports showed only browser-extension origins (Typekit fonts, a `data:` font, an `eval`); `script-src` still allows
   `'unsafe-inline'`: each page's RSC payload script differs per page and per build, and most pages are rendered or regenerated at run time, so no build step can hash them, and a nonce would make every page render per request. It is a dated exemption, `config/standard/tailoring/TAIL-site-csp-inline.json` (D-343, until 2027-02-19).
2. **The site's Lambda and its front door are outside this tree's stacks**, so no test here proves what CloudFront
   adds; the HSTS, `nosniff`, referrer and frame headers are set by the site (`apps/web/src/platform/security/headers.ts`,
   `apps/web/test/site/security-headers.test.ts`) and were seen live on 19/11.
3. **The redirect distribution accepts HTTP** (`infra/aws/stacks/62-redirect.json`, `ViewerProtocolPolicy:
   allow-all`): it only answers a 301 to the HTTPS origin and reaches no origin, so it serves no content over HTTP.
4. **The services' defaults are not listed**: the engine has no public endpoint since the control plane left (D-323),
   and the stopped runner's settings are covered only by its own tests.
