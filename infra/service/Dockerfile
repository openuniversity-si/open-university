# The infrastructure's service (P3 F1): Python and DBOS, with the migrations of infra/db. The deployer builds it on ARM
# from the repository root (INFRA-SVC 1a); the tag is a hash of infra/service and infra/db.
# The subscription CLIs of the session executor (AWS-SUBSCRIPTION-PROVIDERS: claude -p, codex exec), pinned, from npm in a
# Node stage; only node and the two installed packages are copied, so the final image carries no npm cache.
FROM public.ecr.aws/docker/library/node:22-slim AS clis
RUN npm install -g --prefix /opt/clis --no-audit --no-fund @anthropic-ai/claude-code@2.1.319 @openai/codex@0.167.0 \
    && npm cache clean --force
FROM public.ecr.aws/docker/library/python:3.12-slim
# The forge executor (P4 F2) drives Origin through its CLI, installed by Cursor's installer, which checks the binary's
# SHA-256 before using it; git for the forge's actions that touch branches and for the container executor's checkout
# (P4 F1), whose scripts/cloud/setup.sh unpacks the pinned toolchain with tar and xz into /work, the runner's own; a C
# compiler, as the box has, for the gate's fork server (GATE-SPEED F4: fork-server.test.sh builds its shim with cc); jq, as
# the deploy build has, because deploy.test.sh runs infra/aws/deploy.sh itself, which writes its record with jq (on the runner
# without it, 12 tests of DeployShTests failed on 08/11 and the infrastructure judged a green head red).
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl git xz-utils gcc libc6-dev jq \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL https://downloads.cursor.com/origin/install.sh | ORIGIN_INSTALL_DIR=/opt/origin ORIGIN_BIN_DIR=/usr/local/bin sh \
    && mkdir -p /work && chown nobody:nogroup /work \
    && useradd --uid 10001 --create-home --home-dir /home/tower-check --shell /usr/sbin/nologin tower-check \
    && git config --system --add safe.directory '*'
# CHECK-NOT-ROOT (revisão da arquitetura, achado 14): the runner (uid 0, INFRA-EXE 1d) runs a check's command as
# tower-check, a user with no access to the runner's own environment (/proc/<pid>/environ of a root process) or files; the
# checkout is the check user's for its run, so the runner's own git, as root, is told any repository is safe
COPY --from=clis /usr/local/bin/node /usr/local/bin/node
COPY --from=clis /opt/clis /opt/clis
RUN ln -s /opt/clis/bin/claude /usr/local/bin/claude && ln -s /opt/clis/bin/codex /usr/local/bin/codex
WORKDIR /app
COPY infra/service/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --disable-pip-version-check -r /app/requirements.txt
COPY infra/service/tower_infra /app/tower_infra
COPY infra/db/migrations /app/migrations
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 TOWER_MIGRATIONS=/app/migrations HOME=/tmp
USER nobody
ENTRYPOINT ["python", "-m", "tower_infra"]
CMD ["serve"]
