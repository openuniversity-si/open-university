#!/usr/bin/env bash
# Non-secret local defaults for a cloud or laptop shell. Does not read credential files.
# shellcheck shell=bash
# shellcheck disable=SC2154  # _ou_<owner>_<key> are assigned by _ou_cloud_load's eval, from the registry
_ou_cloud="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/cloud/root-session.sh
source "$_ou_cloud/root-session.sh"
_ou_root="$(cd "$_ou_cloud/../.." && pwd)"
_ou_bin="$_ou_root/.toolchain/bin"
# The pinned toolchain wins even when it is already later on PATH. A host node,
# or a test shim placed in front, must not shadow it. OU_SHIM_GUARD is moved ahead below.
if [[ -d "$_ou_bin" ]]; then
  _ou_path=":${PATH}:"
  _ou_path="${_ou_path//:${_ou_bin}:/:}"
  _ou_path="${_ou_path#:}"
  _ou_path="${_ou_path%:}"
  if [[ -n "$_ou_path" ]]; then
    export PATH="${_ou_bin}:${_ou_path}"
  else
    export PATH="${_ou_bin}"
  fi
  unset _ou_path
fi
# GATE-SPEED F4 (D-122): inside a suite run python3 is the fork server's client (OU_FORK_SERVER/bin), ahead of
# the toolchain; it execs the toolchain's interpreter whenever the fork cannot be the process.
_ou_fork_bin="${OU_FORK_SERVER:-}/bin"
if [[ -n "${OU_FORK_SERVER:-}" && -x "$_ou_fork_bin/python3" ]]; then
  _ou_path=":${PATH}:"
  _ou_path="${_ou_path//:${_ou_fork_bin}:/:}"
  _ou_path="${_ou_path#:}"
  _ou_path="${_ou_path%:}"
  export PATH="${_ou_fork_bin}${_ou_path:+:${_ou_path}}"
  unset _ou_path
else
  _ou_fork_bin=""
fi
# A test may park a tripwire ahead of the toolchain. Only a temporary directory is honored: under /tmp, or under
# $TMPDIR, where a test's tempfile puts it (TX12: a guard there used to be ignored without a word).
# Always move it to the front, including when this file is sourced again.
_ou_guard_temp="${TMPDIR:-}"
_ou_guard_temp="${_ou_guard_temp%/}"
if [[ -n "${OU_SHIM_GUARD:-}" && -d "${OU_SHIM_GUARD}" ]] &&
  [[ "${OU_SHIM_GUARD}" == /tmp/* || ( "$_ou_guard_temp" == /?* && "${OU_SHIM_GUARD}" == "$_ou_guard_temp"/* ) ]]; then
  _ou_path=":${PATH}:"
  _ou_path="${_ou_path//:${OU_SHIM_GUARD}:/:}"
  _ou_path="${_ou_path#:}"
  _ou_path="${_ou_path%:}"
  export PATH="${OU_SHIM_GUARD}:${_ou_path}"
  unset _ou_path
fi
unset _ou_guard_temp
if [[ -n "$_ou_fork_bin" ]]; then
  export OU_PYTHON="$_ou_fork_bin/python3"
elif [[ -x "$_ou_bin/python3" ]]; then
  export OU_PYTHON="$_ou_bin/python3"
elif [[ -x /usr/bin/python3 ]]; then
  export OU_PYTHON=/usr/bin/python3
else
  export OU_PYTHON=python3
fi
unset _ou_cloud _ou_bin _ou_fork_bin
# X1 (D-022): the versioned hooks push each commit alone as it is made (scripts/lib/hooks_path.py install sets
# core.hooksPath to push-guard.hooks_path when the checkout has none). Never fails the shell.
if [[ -e "$_ou_root/.git" && -z "$(git -C "$_ou_root" config --get core.hooksPath 2>/dev/null)" ]]; then
  "$OU_PYTHON" "$_ou_root/scripts/lib/hooks_path.py" install --root "$_ou_root" >/dev/null || true
fi
# CENSO-NO-MANIFESTO 3bis: a checkout that skipped setup.sh still gets the regenerate merge driver of .gitattributes.
if [[ -e "$_ou_root/.git" ]] && ! git -C "$_ou_root" config --get-regexp '^merge\..*\.driver$' 2>/dev/null | grep -q merge-regenerate; then
  "$OU_PYTHON" "$_ou_root/scripts/lib/merge_regenerate.py" install --root "$_ou_root" >/dev/null || true
fi

# D-068: every tunable of this file is a registry entry (config/registry/cloud.json). A value is read only by the
# branch that needs it, and only when the environment does not already carry the result of that branch (a registry read
# costs a process); each value named becomes the array _ou_<owner>_<key>, "-" read as "_" (a scalar has one element).
# NANO-UNBLOCK (D-070): a failed read (a rate-limited change store, say) prints one classified line, FAIL env: with
# config.py's reason, and returns 1. Every caller returns with it (a top-level return ends the source with 1), so
# nothing runs on an unset value.
_ou_cloud_load() {
  local found assignments failed="FAIL env: scripts/cloud/env.sh cannot read $* from the registry"
  found="$("$OU_PYTHON" "$_ou_root/scripts/lib/config.py" get "$@" 2>&1)" || {
    echo "$failed: ${found##*$'\n'}" >&2
    return 1
  }
  # config.py answers on its last line (one JSON document); a line above it came from its stderr and is passed on.
  if ! assignments="$(printf '%s\n' "${found##*$'\n'}" | "$OU_PYTHON" -c '
import json, shlex, sys
try:
    found = json.load(sys.stdin)
except ValueError:
    raise SystemExit(1)
# config.py prints the bare value for one name and {name: value} for several.
for name, value in (found if len(sys.argv) > 2 else {sys.argv[1]: found}).items():
    values = value if isinstance(value, list) else [value]
    print("_ou_" + name.replace(".", "_").replace("-", "_") + "=(" + " ".join(shlex.quote(str(item)) for item in values) + ")")
' "$@")" || [[ -z "$assignments" ]]; then
    echo "$failed: config.py did not answer with JSON" >&2
    return 1
  fi
  [[ "$found" != *$'\n'* ]] || printf '%s\n' "${found%$'\n'*}" >&2
  eval "$assignments"
}

# F81: an Origin CLI off PATH (a fresh lane shell) is looked up in origin-client.cli_dirs and its directory appended
# to PATH, so a lane no longer exports PATH=~/.local/bin first. Pinned ($OU_ORIGIN_CLI) or on PATH: nothing is read.
# A convenience, not a requirement: a failed read leaves PATH as it was and the source goes on.
if [[ -z "${OU_ORIGIN_CLI:-}" ]] && ! command -v origin >/dev/null 2>&1 &&
  _ou_cloud_load origin-client.cli origin-client.cli_dirs 2>/dev/null; then
  for _ou_dir in "${_ou_origin_client_cli_dirs[@]}"; do
    _ou_dir="${_ou_dir/#\~/$HOME}"
    if [[ -x "$_ou_dir/${_ou_origin_client_cli[0]}" ]]; then
      export PATH="${PATH:+$PATH:}$_ou_dir"
      break
    fi
  done
  unset _ou_dir
fi

# A cloud egress proxy (HTTPS_PROXY or https_proxy set): Node's built-in fetch ignores it unless
# NODE_USE_ENV_PROXY=1 (https://nodejs.org/api/cli.html#node_use_env_proxy1). That prints undici's
# experimental EnvHttpProxyAgent warning, code UNDICI-EHPA, to stderr; --disable-warning silences that
# one code only (https://nodejs.org/api/cli.html#--disable-warningcode-or-type). Loopback stays direct:
# undici reads no_proxy before NO_PROXY, so each one that is set gets the missing loopback names
# appended (NO_PROXY is created when neither is). Without a proxy nothing here is set.
_ou_proxy_env=NODE_USE_ENV_PROXY
ou_node_env_proxy() {
  [[ -n "${HTTPS_PROXY:-}${https_proxy:-}" ]] || return 0
  # Already applied by a parent shell (the exports below reach children): nothing left to read or append.
  if [[ "${NODE_USE_ENV_PROXY:-}" == 1 && "${NODE_OPTIONS:-}" == *"--disable-warning="* ]]; then
    return 0
  fi
  _ou_cloud_load cloud.proxy_direct_hosts cloud.proxy_silenced_warning || return 1
  local _ou_proxy_warning="--disable-warning=${_ou_cloud_proxy_silenced_warning[0]}"
  local _ou_proxy_direct=("${_ou_cloud_proxy_direct_hosts[@]}")
  export "$_ou_proxy_env=1"
  case " ${NODE_OPTIONS:-} " in
    *" $_ou_proxy_warning "*) ;;
    *) export NODE_OPTIONS="${NODE_OPTIONS:+$NODE_OPTIONS }$_ou_proxy_warning" ;;
  esac
  local name value host
  for name in NO_PROXY no_proxy; do
    [[ -n "${!name+set}" || ( $name == NO_PROXY && -z "${no_proxy+set}" ) ]] || continue
    value="${!name:-}"
    for host in "${_ou_proxy_direct[@]}"; do
      case ",$value," in
        *",$host,"*) ;;
        *) value="${value:+$value,}$host" ;;
      esac
    done
    export "$name=$value"
  done
}
ou_node_env_proxy || return 1
# setup.sh writes these to CLAUDE_ENV_FILE. Only the names ou_node_env_proxy set; never the proxy URL.
ou_node_env_proxy_exports() {
  [[ -n "${HTTPS_PROXY:-}${https_proxy:-}" ]] || return 0
  local name
  for name in "$_ou_proxy_env" NODE_OPTIONS NO_PROXY no_proxy; do
    [[ -z "${!name+set}" ]] || printf 'export %s=%q\n' "$name" "${!name}"
  done
}

# shellcheck source=scripts/lib/gate-isolation.sh
source "$_ou_root/scripts/lib/gate-isolation.sh"
# D-064 (b): one local test database per checkout, so concurrent gates in different worktrees never
# reset each other's schema. Created on demand by ou_test_db_ensure (gate-local, setup.sh).
if [[ -z "${TEST_DATABASE_URL:-}" ]]; then
  _ou_cloud_load cloud.postgres_host cloud.postgres_port || return 1
  TEST_DATABASE_URL="postgresql://postgres@${_ou_cloud_postgres_host[0]}:${OU_POSTGRES_PORT:-${_ou_cloud_postgres_port[0]}}/$(ou_test_db_name "$_ou_root")"
fi
if [[ -z "${APP_DATABASE_URL_CONTAINER_UNPOOLED:-}" ]]; then
  APP_DATABASE_URL_CONTAINER_UNPOOLED="$TEST_DATABASE_URL"
fi
export TEST_DATABASE_URL APP_DATABASE_URL_CONTAINER_UNPOOLED
# uid 0: the default slot checkout (~/.cache under /root, mode 0700) is not traversable by the unprivileged
# uids that script tests drop to (initdb as ou-postgres, the uid 65534 assertions). setup.sh creates this 0755.
if [[ ${EUID} -eq 0 && -z "${GATE_CHECKOUT_ROOT:-}" ]]; then
  _ou_cloud_load cloud.root_gate_checkout_root || return 1
  export GATE_CHECKOUT_ROOT="${_ou_cloud_root_gate_checkout_root[0]}"
fi

# gate-local calls this by name. An already-answering server (Docker or otherwise) is left alone.
pgtools_start() {
  if command -v psql >/dev/null 2>&1 && psql "$TEST_DATABASE_URL" -qtAc 'select 1' >/dev/null 2>&1; then
    return 0
  fi
  "$OU_PYTHON" "$_ou_root/scripts/cloud/postgres.py" ensure && ou_test_db_ensure "${TEST_DATABASE_URL:-}"
}
command -v pgtools_start >/dev/null
