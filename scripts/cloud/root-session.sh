# shellcheck shell=bash
# Sourced before the first git command when the process might be uid 0.
# A non-root shell returns immediately. The exports come from session_identity.py
# (git safe.directory, npm lifecycle uid, HOME and XDG). No secret is printed.
# exit runs only when this file is executed instead of sourced; shellcheck assumes return always leaves.
# shellcheck disable=SC2317
if [[ "${EUID}" -ne 0 || -n "${OU_ROOT_SESSION:-}" ]]; then
  return 0 2>/dev/null || exit 0
fi

_ou_identity="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../lib/session_identity.py"
if [[ -x /usr/bin/python3 ]]; then
  _ou_python=/usr/bin/python3
else
  _ou_python=python3
fi
eval "$("${_ou_python}" "${_ou_identity}" export)"
export OU_ROOT_SESSION=1
unset _ou_identity _ou_python
