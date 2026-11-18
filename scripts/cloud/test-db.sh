#!/usr/bin/env bash
# D-064 (b): the local test database of a checkout (engine-cloud). Sourced by env.sh and by the gate's isolation
# library, which passes both functions on to the gate (D-322: the environment no longer reaches into the gate).
# - ou_test_db_name: the local test database is derived from the checkout path, so one gate's
#   schema reset, migrate and seed never touch another worktree's database.
# - ou_test_db_ensure: creates that database on demand in the shared local PostgreSQL.
# shellcheck shell=bash

# tower_test_<10 hex of sha256(checkout path)>. Hex never starts with "g", so it cannot match the
# integration databases (tower_test_g<random>) that test/int-teardown.ts creates and drops.
ou_test_db_name() {
  local path="${1:?checkout path}" digest
  digest="$(printf '%s' "$path" | sha256sum)" || return
  printf 'tower_test_%s\n' "${digest:0:10}"
}

# Creates the database named in TEST_DATABASE_URL when it is missing. Local PostgreSQL only: the server is one of
# cloud.test_db_hosts (an optional :port after it); any other URL is refused with cloud.test_db_refused_status.
_ou_test_db_config="$(dirname "${BASH_SOURCE[0]}")/../lib/config.py"
ou_test_db_ensure() {
  local url="${1:-${TEST_DATABASE_URL:-}}" name admin rules refused hosts server host port item known=""
  rules="$("${OU_PYTHON:-python3}" "$_ou_test_db_config" get cloud.test_db_refused_status cloud.test_db_hosts |
    "${OU_PYTHON:-python3}" -c 'import json, sys
found = json.load(sys.stdin)
print(found["cloud.test_db_refused_status"])
print("\n".join(found["cloud.test_db_hosts"]))')" || {
    echo "ou_test_db_ensure: cannot read cloud.test_db_hosts from the registry" >&2
    return 1
  }
  refused="${rules%%$'\n'*}"
  hosts="${rules#*$'\n'}"
  server="${url#*://}"
  server="${server%/*}"
  server="${server##*@}"
  host="${server%%:*}"
  port="${server#"$host"}"
  while IFS= read -r item; do
    [[ "$item" != "$host" ]] || known=yes
  done <<<"$hosts"
  [[ "$url" =~ ^postgres(ql)?://[^/]*@[^/]*/[A-Za-z0-9_]+$ && -n "$known" && ( -z "$port" || "$port" =~ ^:[0-9]+$ ) ]] || {
    echo "ou_test_db_ensure: TEST_DATABASE_URL is not a local PostgreSQL database" >&2
    return "$refused"
  }
  name="${url##*/}"
  admin="${url%/*}/postgres"
  [[ "$(psql "$admin" -qtAc "select 1 from pg_database where datname = '$name'" 2>/dev/null)" == 1 ]] && return 0
  # A concurrent creator of the same name loses with "already exists"; the re-check below accepts it.
  psql "$admin" -qtAc "create database \"$name\"" >/dev/null 2>&1 || true
  [[ "$(psql "$admin" -qtAc "select 1 from pg_database where datname = '$name'" 2>/dev/null)" == 1 ]] || {
    echo "ou_test_db_ensure: could not create local test database $name" >&2
    return 1
  }
}
