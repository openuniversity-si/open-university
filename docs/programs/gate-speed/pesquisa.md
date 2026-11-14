# gate-speed — pesquisa

Reuses [GATE-SPEED's research](../../units/GATE-SPEED/research.md) (Bazel, Buck2, TAP, merge queues); this page adds
what the test-management framing needs: execution cost, coverage and flakes.

## Quem faz melhor
1. **Google TAP with Bazel** ([Memon et al., "Taming Google-scale continuous testing", ICSE-SEIP 2017](https://research.google/pubs/taming-google-scale-continuous-testing/)):
   hermetic tests, content-addressed results, only affected tests run; a test result is reused for identical inputs.
2. **Stripe** ([Running three hours of Ruby tests in under three minutes, 2019](https://stripe.com/blog/distributed-ruby-testing)):
   the code is preloaded once and workers fork per test file, so start-up is paid once; tests are distributed per test,
   not per suite, so the slowest unit of work bounds the wall.
3. **Django's and pytest-xdist's parallel runners** ([Django `test --parallel`](https://docs.djangoproject.com/en/5.2/ref/django-admin/#cmdoption-test-parallel),
   [pytest-xdist](https://pytest-xdist.readthedocs.io/)): one worker per core, fork start method, imports done before the
   fork; tests sharded by item, not by file.
4. **Coverage at Google and coverage.py** ([Ivanković et al., "Code coverage at Google", FSE 2019](https://research.google/pubs/code-coverage-at-google/),
   [coverage.py subprocess measurement](https://coverage.readthedocs.io/en/latest/subprocess.html)): coverage measured
   per change and shown with it; every Python subprocess measured through `process_startup` in a sitecustomize.
5. **Flaky tests at Google** ([Micco, 2016](https://testing.googleblog.com/2016/05/flaky-tests-at-google-and-how-we.html))
   and Meta's probabilistic flakiness score ([2020](https://engineering.fb.com/2020/12/10/developer-tools/probabilistic-flakiness/)):
   a flake is measured as a rate, owned, and never silently retried into a pass.

## Encaixe em nós
- **Copy:** content-addressed results (we have them, D-093); coverage through coverage.py's `process_startup` in the
  hermetic sitecustomize the tests already load (done by this program's diagnóstico); a flake rate from repeated cold
  runs, routed through the existing defect register.
- **Adapt:** Stripe's and Django's preloaded fork server to our Python tests (start-up and imports are most of our cost),
  and per-test distribution instead of per-script; fixture repositories built once and copied, and in-memory doubles
  where git itself is not under test (GATE-SPEED wave 2, R2 A3).
- **Does not fit now:** remote execution and a cache shared between boxes need a server (free tier only, one e2-micro);
  predictive (ML) test selection needs history volume we do not have. Both return with the merge queue of about 1,000
  PRs a day, which this program does not build.
