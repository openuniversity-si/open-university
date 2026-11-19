#!/usr/bin/env bash
# The deployer's logic (D-303; DEP1): what the CodeBuild project tower-infra-deploy runs after it cloned the base head.
# It used to be inline in bootstrap.json's buildspec, which only the Torre can change; it lives in the repo now, so a
# merged PR changes it. Behaviour is the buildspec's: build the image of each infra/<name>/Dockerfile into tower-<name>,
# deploy each infra/aws/stacks/NN-name.json as tower-app-name, write /tower/deploy/last-sha only when everything
# succeeded, and exit non-zero otherwise. New: the outcome goes to /tower/deploy/last-build (compact JSON, at most 3 KB),
# so a session can read WHY a build failed through the port's GET /v1/deploy/status without any AWS credential.
#
# Environment: IMAGE_REGISTRY, CFN_EXEC_ROLE_ARN (the project's), CODEBUILD_BUILD_ID (the build's), DEPLOY_REPO (the
# clone, default "repo"), DEPLOY_PARALLEL (stacks at once, default 3), DEPLOY_BUDGET_S (default 1080: the project's timeout
# less a margin; no stack starts whose last duration exceeds what is left of it), CODEBUILD_START_TIME (ms; the budget's
# zero), DEPLOY_TAIL_CHARS (default 1500), DEPLOY_RECORD_MAX_BYTES (default 3000).
# DEP7 (the slow path, docs/operations/aws.md 22.4): the build is SELECTIVE (scripts/lib/deploy_classify.py classifies
# last-sha..HEAD; only the stacks it names, and the stacks that need them, are deployed, and the image only when the diff
# touches it; DEPLOY_TARGETS=a,b or all overrides), skips a stack whose template and image are the ones last applied
# (hashes kept in last-build: the deployer may write nothing else), builds the image with the previous one as cache, runs
# the SMOKE (scripts/deploy-smoke; DEPLOY_SMOKE_CMD replaces it, "none" skips) after the stacks and ROLLS BACK the stacks it
# touched (the previous sha's templates and images) when it is red, and BISECTS a failed batch: last-build carries
# bisect={good,bad}; the next build deploys the first half of the batch's slow commits, then the other half, until one commit
# is the culprit ({culprit,...}); it records seconds, usd (DEPLOY_PRICE_PER_MINUTE, default 0.005), targets, batch and rolled_back.
# DEP7-BISECT-FIX (docs/operations/aws.md 22.8): a bisection never blocks for ever. It is DISCARDED when its epoch is not
# BISECT_EPOCH (a one-time reset: raise the constant to ignore every state an older deploy.sh left, e.g. one started by the
# ACK smoke, which no longer fails builds), when it has lived DEPLOY_BISECT_MAX_BUILDS builds (default 8), when its bad sha is
# no longer in the history of the base head or its good sha is not last-sha. A culprit never blocks the next build: that build
# deploys the CURRENT head; green clears bisect and culprit and moves last-sha to the head, red bisects again. A midpoint that
# is adjacent to bad (or the only slow commit) IS bad: it is deployed as the final step, and when it fails it is the culprit.
# last-build carries bisect_epoch, and bisect.reason (why the state exists or why the earlier one was dropped).
# DEP7-HEAD-FIRST (aws.md 22.8): after a failed batch the next build deploys the CURRENT head first when it moved past the failed
# build's head (a later commit often fixes it, or the failure was transient); only if that fails too, or the head did not move,
# does the bisection start. DEP7-NEW-HEAD-FIRST: this is keyed to a sha (bisect.head_tried_sha = the newest base head that failed), not
# once per state: whenever the base head differs from it (a commit landed, also in the middle of a bisection) the current head is deployed
# before any midpoint; red bisects (last-sha, that head], so a midpoint is never chosen while a newer, untried head exists. The control scripts (deploy_classify, deploy-smoke) always come from
# the HEAD checkout ($ctl, a copy of the head's scripts/ taken before any midpoint is checked out): a midpoint's templates and
# images come from the midpoint's tree ($repo), its old scripts never run.
# SLOW-PATH-NO-ROLLOUT-WAIT (aws.md 22.10; Daniel 10/11: a 981 s cycle was about 14 minutes of two ECS rollouts, waited one after
# the other). The ECS rollout is off the build's clock: a stack with an AWS::ECS::Service that exists is STARTED (its change set
# created and executed) and not waited, and the build ends `rolling` with last-sha untouched and last-build.rolling = {head, until,
# stacks: {name: {t0, hash}}, changed, prev}: what the next build verifies and what a red smoke would roll back. That build is rung
# when each stack's rollout is seen (its new task says it is up, platform.deploy.task_up, or the CloudFormation event the port
# records says the stack ended, whichever is first; both wake the service; `until` is the safety of a rollout that says neither),
# waits in its own seconds for a stack still in its operation (wait:<stack>: the old task's drain) and
# VERIFIES: a rolled stack at the head and *_COMPLETE is done (its seconds go to last-build.rollout, the wait to rollout_wait_s); one
# that is not (the ECS circuit breaker failed the update and CloudFormation rolled the stack back) fails the build exactly as a
# failed stack does; then the smoke, the rollback of everything the two builds changed when it is red, and last-sha. A stack found
# in an operation is waited first (a build that came before the end). A stack another stack of the batch must have complete (a hard
# edge), a bisection and DEPLOY_ROLLOUT_WAIT=1 wait inside the build, as before.
# And a CODE-ONLY landing rings no rollout at all (code_live): a batch whose only slow target is the service image for files of
# tower_infra, whose code is the bundle of deploy.live_code, which both ECS tasks reloaded in place and which a task ECS starts
# later boots, builds no image and leaves the service and runner stacks alone: its cycle is the classification and the checks.
BISECT_EPOCH=2
set -u
# DEPLOY-FROM-GITHUB (the migration, 14/11): the build that verifies a `rolling` one (the smoke, the rollback, last-sha) is rung by
# the service's autodeploy, which reads the forge's pushes on Origin and only while deploy.auto is on. A build of a repository on
# GitHub is rung by its doorbell job once per merge, and the service rings nothing after it: a build that ended `rolling` left
# last-sha behind until the next merge (tower-infra-deploy:41a85a3e, 14/11 06:32 UTC: succeeded, last-sha still b77f1f52). So a
# build of a GitHub repository waits its own rollouts, as DEPLOY_ROLLOUT_WAIT=1 does, and moves last-sha itself; an explicit
# DEPLOY_ROLLOUT_WAIT (0 or 1) still decides.
if [[ -z "${DEPLOY_ROLLOUT_WAIT:-}" && "${ORIGIN_REPO_URL:-}" == https://github.com/* ]]; then
  DEPLOY_ROLLOUT_WAIT=1
  echo "rollouts: waited inside the build: $ORIGIN_REPO_URL is on GitHub, and no service rings the build that would verify them"
fi

repo="${DEPLOY_REPO:-repo}"
# MEDIA-REPLICA (RISK-media-single-account, 19/11): a stack named in infra/aws/regions.json (name -> region) lives in that
# region, and every CloudFormation call of the apply, the wait, the events and the rollback says so for it (--region;
# deploy_stacks fills this); every other stack is in the build's own region, as before. The service and runner stacks'
# own readers (prev_params, code_live_stacks, port_fast_owned) name no region: those ECS stacks are never moved
declare -A at_region=()
tail_chars="${DEPLOY_TAIL_CHARS:-1500}"
max_bytes="${DEPLOY_RECORD_MAX_BYTES:-3900}"
(( max_bytes > 4000 )) && max_bytes=4000  # DEP-WATCHDOG: last-build is ALWAYS <= 4000 bytes (SSM Standard refuses > 4096)
build_id="${CODEBUILD_BUILD_ID:-unknown}"
# DEPLOY-FEWER-FORKS: the clock is bash's own (EPOCHSECONDS, bash 5; the build image and the runner have 5.2)
[[ -n "${EPOCHSECONDS:-}" ]] || { echo "deploy.sh needs bash 5 (EPOCHSECONDS)" >&2; exit 2; }
started="$EPOCHSECONDS"
work="$(mktemp -d)"
output="$work/output"
head0="$(git -C "$repo" rev-parse HEAD 2>/dev/null || echo unknown)"
: >"$work/steps"
# the previous build's record: the stack durations the deadline guard compares with the budget, kept across builds
bisect_max_builds="${DEPLOY_BISECT_MAX_BUILDS:-8}"
prev_build="$(aws ssm get-parameter --name /tower/deploy/last-build --query Parameter.Value --output text 2>/dev/null || echo '{}')"

# BOOTSTRAP-DRIFT (BOOTSTRAP-MIRROR; the review's findings 26 and 27; req-667-reach, 13/11): the tower-bootstrap stack, which only
# the Torre applies, read back (get-template: the DeployerRole may since req-667-reach) and compared with its mirror,
# infra/aws/bootstrap.json, in the canonical form test_infra_aws hashes (keys sorted, no space). The verdict is one step of the
# record, last-build.bootstrap: same, drift or unread; read beside the build, in the background, it never fails nor slows
# one; a drift is the Torre's to read in last_build (GET /v1/deploy/status).
canonical_sha() {
  python3 -c 'import hashlib, json, sys
t = json.load(sys.stdin)
t = json.loads(t) if isinstance(t, str) else t
print(hashlib.sha256(json.dumps(t, sort_keys=True, separators=(",", ":")).encode()).hexdigest())'
}
bootstrap_drift() {
  local applied mirror
  applied="$(timeout 60 aws cloudformation get-template --stack-name tower-bootstrap --query TemplateBody --output json 2>/dev/null | canonical_sha 2>/dev/null)" || applied=""
  mirror="$(canonical_sha <"$repo/infra/aws/bootstrap.json" 2>/dev/null)" || mirror=""
  if [[ -z "$applied" || -z "$mirror" ]]; then echo unread
  elif [[ "$applied" = "$mirror" ]]; then echo same
  else echo drift; fi
}
( bootstrap_drift >"$work/bootstrap.tmp" 2>/dev/null && mv "$work/bootstrap.tmp" "$work/bootstrap" ) >/dev/null 2>&1 &
bootstrap_pid=$!

# AWS-SPEND (D-331, VAL-aws-200): the account's unblended spend for the month to date, from Cost Explorer
# (ce:GetCostAndUsage, US$ 0.01 a call, in us-east-1, its only endpoint), AT MOST ONCE PER UTC DAY: a build whose earlier
# record already holds today's reading carries it and calls nothing. last-build.spend = {day, from, usd}; read beside the
# build, in the background, like the bootstrap's drift: a refused or failed read keeps the earlier reading and never fails
# nor slows a build. The engine has no AWS credential: it records the reading from the port's status
# (`scripts/deploy status --json | scripts/spend record`) and scripts/model judges VAL-aws-200 by that snapshot.
spend_day="$(date -u +%F)"
# SPEND-PARSE: the version of the reading's parser; a refusal of an older parser does not hold the day (2: a credit or an
# exponent is a reading, #317)
spend_parse=2
spend_read() {
  local from="${spend_day:0:8}01" until usd
  until="$(date -u -d "$spend_day + 1 day" +%F 2>/dev/null)" || return 1
  local said=0
  usd="$(timeout 30 aws ce get-cost-and-usage --region us-east-1 --time-period "Start=$from,End=$until" --granularity MONTHLY \
    --metrics UnblendedCost --query 'ResultsByTime[0].Total.UnblendedCost.Amount' --output text 2>"$work/spend.err")" || said=$?
  # a credit can make the month negative, and the CLI may print a tiny amount with an exponent: both are a number
  if (( said != 0 )) || ! [[ "$usd" =~ ^-?[0-9]+(\.[0-9]+)?([eE][-+]?[0-9]+)?$ ]]; then
    # SPEND-WHY (VAL-aws-200): the class of the refusal, never the CLI's text, so the record says why there is no reading
    local why=other
    if (( said == 124 )); then why=timeout
    elif grep -qiE 'AccessDenied|not authorized' "$work/spend.err" 2>/dev/null; then why=access-denied
    elif grep -qiE 'not enabled|DataUnavailable|opt.?in' "$work/spend.err" 2>/dev/null; then why=not-enabled
    elif (( said == 0 )); then why=no-amount; fi
    # no-amount keeps what the CLI printed instead, cut to 24 characters of [A-Za-z0-9.+-] (an amount or None, no secret)
    local seen=""; [[ "$why" = no-amount ]] && seen="$(printf '%s' "$usd" | tr -cd 'A-Za-z0-9.+-' | cut -c1-24)"
    jq -nc --arg day "$spend_day" --arg why "$why" --arg seen "$seen" --argjson parse "$spend_parse" \
      '{day: $day, why: $why, parse: $parse} + (if $seen != "" then {seen: $seen} else {} end)' >"$work/spend.why"
    return 1
  fi
  jq -nc --arg day "$spend_day" --arg from "$from" --arg usd "$usd" '{day: $day, from: $from, usd: ($usd | tonumber * 100 | round / 100)}'
}
spend_pid=""
# a day already read, or already refused by this parser (spend_error, SPEND-WHY, SPEND-PARSE), calls Cost Explorer no
# more that day
if [[ "$(jq -r '.spend.day? // empty' <<<"$prev_build" 2>/dev/null)" != "$spend_day" &&
      "$(jq -r '"\(.spend_error.day? // "")/\(.spend_error.parse? // "")"' <<<"$prev_build" 2>/dev/null)" != "$spend_day/$spend_parse" ]]; then
  ( spend_read >"$work/spend.tmp" 2>/dev/null && mv "$work/spend.tmp" "$work/spend" ) >/dev/null 2>&1 &
  spend_pid=$!
fi

# slow_commits <good> <bad>: the commits of (good, bad] that touch what the slow path deploys, oldest first.
slow_commits() {
  git -C "$repo" rev-list --reverse "$1..$2" -- infra/aws infra/service infra/db infra/ingress services/runner 2>/dev/null
}

# redact: the values of the environment variables that name a secret, then anything shaped like one.
redact() {
  # DEPLOY-FEWER-FORKS: stdin and the environment are read by bash itself (read, compgen -e), not by cat and env; the
  # environment is read at each call, so a secret exported during the build is redacted too
  local text="" name value
  IFS= read -r -d '' text || true
  text="${text%"${text##*[!$'\n']}"}"  # as $(cat): no trailing newlines
  for name in $(compgen -e); do
    case "$name" in
      *TOKEN* | *SECRET* | *PASSWORD* | *API_KEY* | *CREDENTIAL* | AWS_ACCESS_KEY_ID)
        value="${!name}"; if [[ ${#value} -ge 8 ]]; then text="${text//"$value"/[redacted]}"; fi ;;
    esac
  done
  printf '%s' "$text" | sed -E \
    -e 's/([Bb]earer|[Bb]asic)[[:space:]]+[A-Za-z0-9._~+\/=-]{8,}/\1 [redacted]/g' \
    -e 's/(AKIA|ASIA)[A-Z0-9]{16}/[redacted]/g' \
    -e 's/([A-Za-z0-9_-]*([Tt][Oo][Kk][Ee][Nn]|[Ss][Ee][Cc][Rr][Ee][Tt]|[Pp][Aa][Ss][Ss][Ww][Oo][Rr][Dd]|[Aa][Pp][Ii][_-]?[Kk][Ee][Yy]|[Cc][Rr][Ee][Dd][Ee][Nn][Tt][Ii][Aa][Ll]|[Aa][Uu][Tt][Hh][Oo][Rr][Ii][Zz][Aa][Tt][Ii][Oo][Nn])[A-Za-z0-9_-]*)([=:][[:space:]]*|[[:space:]]+)[^[:space:]"'"'"',;]{4,}/\1\3[redacted]/g' \
    -e 's/[A-Za-z0-9+_-]{41,}/[redacted]/g'
}

# bytes_of <text>: its size in BYTES (SSM Standard refuses a value over 4096; ${#x} counts characters).
bytes_of() { local LC_ALL=C; printf '%s' "${#1}"; }  # DEPLOY-FEWER-FORKS: bash counts bytes under the C locale

# steps_json: the steps file ($work/steps: name, status running|ok|failed, t0, t1 per line) as a compact array [{n,s,t}].
steps_json() {
  local arr f
  # DEPLOY-FEWER-FORKS: one jq over the whole file (-Rs), not one per line piped into a second that slurps
  arr="$(jq -Rsc --argjson now "$EPOCHSECONDS" 'split("\n") | map(select(length > 0) | split("\t") | {n: .[0], s: .[1], t: ((if (.[3] | tonumber) > 0 then (.[3] | tonumber) else $now end) - (.[2] | tonumber))}) | .[-24:]' \
    "$work/steps" 2>/dev/null)" || arr='[]'
  [[ -n "$arr" ]] || arr='[]'
  # a failed step carries `e`: its own last lines of output (step_err), so the status says WHY, not only where
  for f in "$work"/err.*; do
    [[ -s "$f" ]] || continue
    arr="$(jq -c --arg k "${f##*/err.}" --rawfile e "$f" 'map(if .s == "failed" and (.n | gsub("[^A-Za-z0-9_-]"; "_")) == $k then . + {e: $e} else . end)' <<<"$arr" 2>/dev/null)" || true
  done
  echo "${arr:-[]}"
}
# step_mark/step_err: a step's own output is what $output gained since step_begin; on failure its last 15 lines (redacted, 700 chars) are kept.
# DEPLOY-FEWER-FORKS: a file's text with no cat, quiet and failing when it is not there (as `cat <f> 2>/dev/null`)
# rw_file <var> <file>: the file's text into <var> by bash's read (no fork), empty when it is not there; trailing newlines
# dropped, as $(<file) does
rw_file() {
  local -n __into="$1"; __into=""
  [[ -f "$2" && -r "$2" ]] || return 0
  IFS= read -r -d '' __into <"$2" || true
  __into="${__into%"${__into##*[!$'\n']}"}"
}
slurp() { [[ -f "$1" && -r "$1" ]] || return 1; local text; text="$(<"$1")"; printf '%s' "$text"; }
step_key() { printf '%s' "${1//[^A-Za-z0-9_-]/_}"; }
step_err() {
  local k mark; k="$(step_key "$1")"; mark="$(slurp "$work/mark.$k" || echo 0)"
  tail -n +$((mark + 1)) "$output" 2>/dev/null | tail -n 15 | tr -d '\000-\010\013-\037' | redact | cut -c1-240 | tail -c 700 >"$work/err.$k"
}
# step_begin <name>: DEP-WATCHDOG: a step starts; last-build is rewritten (status in_progress) so a reader sees where the build is.
step_begin() {  # DEPLOY-FEWER-FORKS: no tr, no date: bash's own expansion and clock
  local lines; lines="$(wc -l <"$output" 2>/dev/null)"; printf '%s' "${lines//[[:space:]]/}" >"$work/mark.${1//[^A-Za-z0-9_-]/_}"
  printf '%s\trunning\t%s\t0\n' "$1" "$EPOCHSECONDS" >>"$work/steps"; progress
}
# step_end <name> <exit code>: the step ends ok or failed; the first failed step names the failure.
step_end() {
  local st=ok; [[ "$2" = 0 ]] || st=failed
  awk -F'\t' -v OFS='\t' -v n="$1" -v s="$st" -v t="$EPOCHSECONDS" '$1 == n && $2 == "running" {$2 = s; $4 = t} {print}' "$work/steps" >"$work/steps.tmp" 2>/dev/null \
    && mv "$work/steps.tmp" "$work/steps"
  [[ "$st" = failed ]] && step_err "$1"
  [[ "$st" = failed && ! -s "$work/failed_step" ]] && echo "$1" >"$work/failed_step"
  # PROGRESS-AT-START: a step that ended ok is said by the next step's start (milliseconds later) or the build's end:
  # the record is ~33 jq calls, and one at each end too was half of a build's 18 (3.2 of a tested deploy's 3.9 s)
  if [[ "$st" = failed ]]; then progress; fi
}
# progress: last-build = in_progress with the current step; never changes the outcome. Skipped when the build already recorded its end.
progress() {
  [[ -f "$work/recorded" ]] && return 0
  record in_progress "$(slurp "$work/head" || echo "$head0")" >/dev/null 2>&1 || true
}

# record <status> <head> <failed...>: the last-build parameter, ALWAYS <= max_bytes (4000: the SSM Standard limit is 4096). When it
# is too big, optional parts go in a fixed order: tail, steps (only the not ok), hashes (with fast_owned), stack timings (with
# rollout and parts), the bisect text; at last a minimal record. A failure to record never
# changes the deploy's outcome; a failed write is retried as the minimal record {status, build_id, ended, base_head, error}.
record() {
  local status="$1" head="$2" ended ended_out tail failed_json json done_json left_json secs_json targets_json rolled_json bisect_json hashes_json fast_owned_json live_json
  local n seconds usd batch steps step_cur fail_step bnote_txt lvl=0 over size lines="${record_tail_lines:-0}" migrate_json rolling_json rollout_json wait_json code_live parts_json port_tpl
  shift 2
  ended="$EPOCHSECONDS"; ended_out="$ended"; [[ "$status" = in_progress ]] && ended_out=0
  # BOOTSTRAP-DRIFT: its verdict in the record; the build's end waits for it (a read of a second, begun at the build's start)
  [[ "$status" = in_progress ]] || wait "${bootstrap_pid:-}" 2>/dev/null || true
  local bootstrap_said=""; [[ -s "$work/bootstrap" ]] && bootstrap_said="$(<"$work/bootstrap")"
  # AWS-SPEND: this build's reading of the month's spend, else the earlier record's (one Cost Explorer call a day at most)
  [[ "$status" = in_progress || -z "${spend_pid:-}" ]] || wait "$spend_pid" 2>/dev/null || true
  local spend_json=""; [[ -s "$work/spend" ]] && spend_json="$(<"$work/spend")"
  if [[ -z "$spend_json" ]]; then
    [[ -n "${prev_spend+x}" ]] || prev_spend="$(jq -c '.spend? | if type == "object" then . else empty end' <<<"$prev_build" 2>/dev/null)"
    spend_json="$prev_spend"
  fi
  [[ -n "$spend_json" ]] || spend_json=null
  local spend_error_json=null; [[ -s "$work/spend.why" ]] && spend_error_json="$(<"$work/spend.why")"
  if [[ "$spend_error_json" = null ]]; then
    spend_error_json="$(jq -c --arg day "$spend_day" '.spend_error? | if type == "object" and .day == $day then . else null end' <<<"$prev_build" 2>/dev/null)"
    [[ -n "$spend_error_json" ]] || spend_error_json=null
  fi
  # RECORD-ONE-JQ: every part of the record from one jq over this build's files and the earlier record, one compact JSON per
  # line: the record was ~33 jq calls (each its own process), 3.2 of a tested deploy's 3.9 s and the CPU the deploy's tests
  # fight for on the runner's two vCPUs
  if (( lines > 0 )); then tail="$(tail -n "$lines" "$output" 2>/dev/null | tr -d '\000-\010\013-\037' | redact | tail -c "$tail_chars")"
  else tail="$(tail -c $((tail_chars * 2)) "$output" 2>/dev/null | tr -d '\000-\010\013-\037' | redact | tail -c "$tail_chars")"; fi
  local hashlines="" livelist="" f parts_out
  for f in "$work"/res/*.hash; do [[ -f "$f" ]] && { rw_file hv "$f"; hashlines+="${f##*/}"$'\t'"$hv"$'\n'; }; done
  for f in "$repo"/infra/aws/stacks/*.json; do [[ -f "$f" ]] || continue; f="${f##*/}"; f="${f%.json}"; livelist+="${f#[0-9]*-}"$'\n'; done
  read_work() { [[ -f "$work/$1" ]] && printf '%s' "$(<"$work/$1")"; return 0; }
  # DEPLOY-FEWER-FORKS: the work files into variables by bash's read, not one $(...) fork of this shell each (~20 a
  # record, a record at each step): the same text, trailing newlines dropped as $(...) did
  local w_done w_left w_rolled w_dirty w_secs w_rollout w_parts w_targets w_bisect w_fast_owned w_migrate w_rolling w_port_tpl w_wait
  local has_bisect=false has_fast_owned=false has_port_tpl=false hv
  rw_file w_done "$work/done"; rw_file w_left "$work/left"; rw_file w_rolled "$work/rolled"; rw_file w_dirty "$work/dirty"
  rw_file w_secs "$work/secs"; rw_file w_rollout "$work/rollout"; rw_file w_parts "$work/parts"
  rw_file w_targets "$work/targets_json"; rw_file w_bisect "$work/bisect"; rw_file w_fast_owned "$work/fast_owned"
  rw_file w_migrate "$work/migrate"; rw_file w_rolling "$work/rolling"; rw_file w_port_tpl "$work/port_tpl"
  rw_file w_wait "$work/rollout_wait"
  [[ -f "$work/bisect" ]] && has_bisect=true; [[ -f "$work/fast_owned" ]] && has_fast_owned=true
  [[ -f "$work/port_tpl" ]] && has_port_tpl=true
  parts_out="$(jq -nr --arg prev "$prev_build" --arg done "$w_done" --arg left "$w_left" \
    --arg rolled "$w_rolled" --arg dirty "$w_dirty" --arg secs "$w_secs" \
    --arg rollout "$w_rollout" --arg parts "$w_parts" --arg targets "$w_targets" \
    --arg bisect "$w_bisect" --argjson has_bisect "$has_bisect" \
    --arg hashlines "$hashlines" --arg live "$livelist" \
    --arg fast_owned "$w_fast_owned" --argjson has_fast_owned "$has_fast_owned" \
    --arg migrate "$w_migrate" --arg rolling "$w_rolling" --arg status "$status" \
    --arg port_tpl "$w_port_tpl" --argjson has_port_tpl "$has_port_tpl" \
    --arg wait "$w_wait" --argjson seconds "$((ended - started))" --arg rate "${DEPLOY_PRICE_PER_MINUTE:-0.005}" '
    def lines($t): $t | split("\n") | map(select(length > 0));
    def doc($t; $d): ($t | try fromjson catch null) // $d;
    def object($t): ($t | try fromjson catch null) | if type == "object" then . else null end;
    (($prev | try fromjson catch {}) | if type == "object" then . else {} end) as $p
    | lines($live) as $live
    | def keep: if ($live | length) > 0 then with_entries(select(.key as $k | $live | index($k | sub("^tower-app-"; "")))) else . end;
    (lines($rolled)) as $rolled
    | (reduce (lines($hashlines)[] | split("\t")) as $h (($p.hashes // {}); . + {($h[0] | sub("\\.hash$"; "")): ($h[1:] | join("\t"))})
       | reduce ($rolled[] | sub("^tower-app-"; "")) as $n (.; del(.[$n]))
       | if ($live | length) > 0 then with_entries(select(.key as $k | $live | index($k))) else . end) as $hashes
    | (if $has_fast_owned then ($fast_owned | try fromjson catch null) else ($p.fast_owned // null) end) as $fo
    | ([$ARGS.positional[] | select(length > 0)]),
      lines($done), lines($left), ((($p.stacks // {}) + doc($secs; {})) | keep), doc($targets; null), $rolled,
      (if $has_bisect then doc($bisect; null) else ($p.bisect // null) end), $hashes, $fo, object($migrate), (if $status == "rolling" or ($status == "succeeded" and (object($rolling) // {}).settling == true) then object($rolling) else null end),
      ((($p.rollout // {}) + doc($rollout; {})) | keep), ((($p.parts // {}) + doc($parts; {})) | keep), lines($dirty),
      (if ($wait | test("^[0-9]+$")) then ($wait | tonumber) else null end),
      ((($seconds / 60 * ($rate | tonumber)) * 1000000 | round) / 1000000)
    | tojson' --args "$@" 2>/dev/null)" || parts_out=""
  { read -r failed_json; read -r done_json; read -r left_json; read -r secs_json; read -r targets_json; read -r rolled_json
    read -r bisect_json; read -r hashes_json
    read -r fast_owned_json; read -r migrate_json; read -r rolling_json; read -r rollout_json; read -r parts_json
    read -r dirty_json; read -r wait_json; read -r usd; } <<<"$parts_out"
  local pair name
  for pair in 'failed_json=[]' 'done_json=[]' 'left_json=[]' 'secs_json={}' targets_json=null 'rolled_json=[]' bisect_json=null \
      'hashes_json={}' fast_owned_json=null migrate_json=null \
      rolling_json=null 'rollout_json={}' 'parts_json={}' 'dirty_json=[]' wait_json=null usd=0; do
    name="${pair%%=*}"
    [[ -n "${!name}" ]] || printf -v "$name" '%s' "${pair#*=}"  # what the one jq did not answer: the empty value
  done
  # STACK-COMMIT-OFF-TAGS: the port template as last applied: this build's apply, else the earlier record's; none once the
  # port stack was rolled back (the next build applies it again)
  if [[ -f "$work/port_tpl" ]]; then port_tpl="$(<"$work/port_tpl")"
  else  # DEPLOY-FEWER-FORKS: the earlier record does not change while the build runs: read once
    [[ -n "${prev_port_tpl+x}" ]] || prev_port_tpl="$(jq -r '.port_tpl // empty' <<<"$prev_build" 2>/dev/null)"
    port_tpl="$prev_port_tpl"
  fi
  [[ $'\n'"$(slurp "$work/rolled")"$'\n' == *$'\n'tower-app-port$'\n'* ]] && port_tpl=""  # DEPLOY-FEWER-FORKS: no grep
  local reload_json=""; [[ -f "$work/reload" ]] && reload_json="$(jq -c 'if type == "object" then . else empty end' "$work/reload" 2>/dev/null)"; [[ -n "$reload_json" ]] || reload_json=null  # FAST-PATH-RELOAD
  local code_live_why; rw_file code_live "$work/code_live"; rw_file code_live_why "$work/code_live_why"  # the bundle a code-only batch was found live by: nothing of it was deployed
  steps="$(steps_json)"
  # DEPLOY-FEWER-FORKS: the running step by bash's read (as the awk did: the last line whose state is running)
  step_cur=""; local step_n step_s step_rest
  if [[ -f "$work/steps" ]]; then
    while IFS=$'\t' read -r step_n step_s step_rest; do [[ "$step_s" = running ]] && step_cur="$step_n"; done <"$work/steps"
  fi
  rw_file fail_step "$work/failed_step"; rw_file bnote_txt "$work/bnote"
  seconds=$((ended - started)); batch=0; [[ -f "$work/batch" ]] && rw_file batch "$work/batch"
  while :; do
    json="$(jq -nc --arg build_id "$build_id" --arg base_head "$head" --arg status "$status" --arg bootstrap "$bootstrap_said" \
      --argjson failed "$failed_json" --argjson done "$done_json" --argjson left "$left_json" --argjson stacks "$secs_json" \
      --argjson started "$started" --argjson ended "$ended_out" --arg tail "$tail" --argjson targets "$targets_json" \
      --argjson rolled "$rolled_json" --argjson bisect "$bisect_json" --argjson epoch "$BISECT_EPOCH" --arg bnote "$bnote_txt" --argjson hashes "$hashes_json" --argjson dirty "$dirty_json" \
      --argjson fast_owned "$fast_owned_json" --argjson migrate "$migrate_json" --argjson rolling "$rolling_json" --argjson rollout "$rollout_json" --argjson parts "$parts_json" --arg port_tpl "$port_tpl" --argjson wait "$wait_json" --arg code_live "$code_live" --arg code_live_why "$code_live_why" --argjson reload "$reload_json" --argjson seconds "$seconds" --argjson usd "$usd" --argjson batch "$batch" --argjson spend "$spend_json" --argjson spend_error "$spend_error_json" \
      --argjson steps "$steps" --arg step "$step_cur" --arg failed_step "$fail_step" --argjson updated "$ended" \
      '{build_id: $build_id, base_head: $base_head, status: $status, failed: $failed, done: $done, left: $left, stacks: $stacks, started: $started, ended: $ended, updated: $updated, step: $step, failed_step: $failed_step, steps: $steps, seconds: $seconds, usd: $usd, targets: $targets, batch: $batch, rolled_back: $rolled, bisect: $bisect, bisect_epoch: $epoch, bisect_note: $bnote, hashes: $hashes, dirty: $dirty, tail: $tail} + (if $fast_owned then {fast_owned: $fast_owned} else {} end) + (if $migrate then {migrate: $migrate} else {} end) + (if $rolling then {rolling: $rolling} else {} end) + (if ($rollout | length) > 0 then {rollout: $rollout} else {} end) + {parts: $parts} + (if $port_tpl != "" then {port_tpl: $port_tpl} else {} end) + (if $wait != null then {rollout_wait_s: $wait} else {} end) + (if $code_live != "" then {code_live: $code_live} else {} end) + (if $code_live_why != "" then {code_live_why: $code_live_why} else {} end) + (if $reload then {reload: $reload} else {} end) + (if $bootstrap != "" then {bootstrap: $bootstrap} else {} end) + (if $spend then {spend: $spend} else {} end) + (if $spend_error then {spend_error: $spend_error} else {} end)' 2>/dev/null)" || json=""
    [[ -n "$json" ]] || break
    size="$(bytes_of "$json")"
    (( size <= max_bytes )) && break
    over=$((size - max_bytes))
    case $lvl in
      0) if (( ${#tail} > over + 16 )); then tail="${tail: $((over + 16))}"; else tail=""; lvl=1; fi ;;
      1) steps="$(jq -c 'map(select(.s != "ok") | if .e then .e |= .[-400:] else . end)' <<<"$steps" 2>/dev/null || echo '[]')"; lvl=2 ;;
      2) hashes_json='{}'; dirty_json='[]'; fast_owned_json=null; lvl=3 ;;
      3) secs_json='{}'; rollout_json='{}'; parts_json='{}'; lvl=4 ;;
      4) bnote_txt=""; steps="$(jq -c 'map(select(.s == "failed") | if .e then .e |= .[-200:] else . end)' <<<"$steps" 2>/dev/null || echo '[]')"; lvl=5 ;;
      5) bisect_json="$(jq -c 'if type == "object" then del(.reason) else . end' <<<"$bisect_json" 2>/dev/null || echo null)"; done_json='[]'; left_json='[]'; lvl=6 ;;
      *) json=""; break ;;
    esac
  done
  if [[ -n "$json" ]] && timeout 60 aws ssm put-parameter --name /tower/deploy/last-build --type String --overwrite --value "$json" >/dev/null 2>"$work/put.err"; then
    return 0
  fi
  # the write failed (or nothing fits): the service must still see the end of the build
  record_minimal "$status" "$head" "${ended_out}" "record too large or refused: $(head -c 120 "$work/put.err" 2>/dev/null | tr -d '\n"\\')"
}

# record_minimal <status> <head> <ended> <error>: {status, build_id, ended, base_head, error} and nothing else.
record_minimal() {
  local json
  json="$(jq -nc --arg build_id "$build_id" --arg base_head "$2" --arg status "$1" --argjson started "$started" --argjson ended "$3" \
    --arg error "${4:0:200}" --arg failed_step "$(slurp "$work/failed_step")" \
    '{build_id: $build_id, base_head: $base_head, status: $status, started: $started, ended: $ended, failed_step: $failed_step, error: $error}')" || return 1
  timeout 60 aws ssm put-parameter --name /tower/deploy/last-build --type String --overwrite --value "$json" >/dev/null
}

ctl="$repo"  # where the control scripts are read from; deploy() points it at a copy of the head's scripts/ before a midpoint checkout

# select_targets <last>: what this batch needs (DEP7). Writes $work/targets (the word all, or the stack names, one per line;
# empty: no slow target), $work/image (1 or 0: build the images) and $work/targets_json for the record. DEPLOY_TARGETS
# (a,b,... or all) wins; an unknown <last> or no classifier means everything, as before DEP7.
select_targets() {
  local last="$1" json="" spec="" t
  if [[ -n "${DEPLOY_TARGETS:-}" ]]; then
    spec="${DEPLOY_TARGETS//,/ }"
  elif [[ "$last" != none ]] && git -C "$repo" cat-file -e "$last^{commit}" 2>/dev/null && [[ -f "$ctl/scripts/lib/deploy_classify.py" ]] \
      && json="$(cd "$repo" && python3 "$ctl/scripts/lib/deploy_classify.py" "$last" HEAD 2>/dev/null)" && jq -e '.slow' <<<"$json" >/dev/null 2>&1; then
    echo "$json" >"$work/classify.json"  # SLOW-PATH-NO-ROLLOUT-WAIT: code_live reads the paths and their targets
    for t in $(jq -r '.slow[]' <<<"$json"); do
      case "$t" in
        slow:stack-all | slow:deployer) spec="$spec all" ;;
        slow:service-image) spec="$spec image service port runner" ;;
        slow:stack-*) spec="$spec ${t#slow:stack-}" ;;
      esac
    done
  else
    spec=all
  fi
  case " $spec " in *" all "*) spec=all ;; esac
  if [[ "$spec" = all ]]; then echo all >"$work/targets"; echo 1 >"$work/image"; else
    tr ' ' '\n' <<<"$spec" | grep -v -e '^$' -e '^image$' >"$work/targets" || true
    case " $spec " in *" image "*) echo 1 >"$work/image" ;; *) echo 0 >"$work/image" ;; esac
  fi
  jq -R 'select(length > 0)' "$work/targets" | jq -sc . >"$work/targets_json"
  echo "targets: $(tr '\n' ' ' <"$work/targets")(image: $(<"$work/image"))"
}

# deploy_stacks: every infra/aws/stacks/NN-name.json as tower-app-name, in the order of infra/aws/order.json (name -> the names
# it needs first; a test keeps it equal to the real Fn::ImportValue use). A stack starts when its needs are done, at most
# DEPLOY_PARALLEL (default 3) at once. A stack whose recorded hash is the head's, in a *_COMPLETE state, is skipped (also the
# resume of an incomplete build; STACK-COMMIT-OFF-TAGS: no commit tag says it any more). Before it starts, a stack whose last recorded duration no longer fits the budget is not started
# (DEPLOY_BUDGET_S, default 1080, counted from CODEBUILD_START_TIME): the build ends `incomplete`, last-sha untouched.
# Fills $failed, and the files done, left and secs (stack -> seconds of the real changes) in $work.
# stack_hash <name>: the hash of what would be applied (template, images, the lambda keys for port); locals of deploy_stacks (tpl, lsig).
# DEP7-CRITICAL-PATH: only what the stack reads: the images its template names (/tower/deploy/image/<name>, $work/img/<name>), and
# for port the lambda keys. It held every image and every package: a new service image dirtied network, data and
# ack-canary, so every service-image cycle redeployed them (42 s + 67 s on the critical path, 108 s beside it) for nothing.
stack_hash() {
  local i
  { cat "${tpl[$1]}"
    for i in $(grep -o '/tower/deploy/image/[A-Za-z0-9_-]*' "${tpl[$1]}" | sort -u); do cat "$work/img/${i##*/}" 2>/dev/null; done
    [[ $1 = port ]] && printf '%s' "$lsig"
    # PARAMS-IN-HASH (#220, 18/11): the stack's values in infra/aws/parameters.json are part of what it is applied with,
    # so a change there alone (media's Cdn off -> on) deploys the stack instead of skipping it as unchanged
    jq -cS --arg n "$1" '.[$n] // empty' "$repo/infra/aws/parameters.json" 2>/dev/null
    # MEDIA-REPLICA: and its region, when regions.json names one (nothing for the others, whose hashes stay as they were)
    [[ -n "${at_region[$1]:-}" ]] && printf 'Region=%s' "${at_region[$1]}"
    [[ ($1 = service || $1 = runner) && -s "$work/livecode" ]] && printf 'LiveCode=%s' "$(<"$work/livecode")"; } | sha256sum | cut -c1-20
}

# DEP7-PORT-FAST-OWNED: port_fast_owned: 0 when applying tower-app-port would change nothing but the S3 key of Lambdas whose code at
# that key the fast path (fastdeploy.py) already put live, so the stack (192 s) is not redeployed: the apply would only rewrite
# $LATEST and publish a version of the code the alias live already runs. Writes $work/fast_owned ({function: {d: digest, v: version,
# at}}: the swaps that stand in for the stack's lagging keys, kept in last-build.fast_owned for the next builds) and the log line;
# else prints why the stack is deployed and returns 1. Every unknown deploys, as before. Evidence, all of it from what the deployer
# already reads (no IAM change):
#  - the stack (describe-stacks): CREATE/UPDATE_COMPLETE, its parameters, and its commit tag, whose 40-port.json must be the head's;
#    DepsKey (the layer: the fast path never swaps it) equal to what this build passes;
#  - the end of its last operation (the newest stack event): a swap before it may have been overwritten by that operation;
#  - for tower-port-api, when its key differs from the stack's parameter (GATE-SHUTDOWN: the port's only Lambda), the newest swap after that end, from the port's GET /v1/deploy/status
#    `fast` (the service's swaps; read like scripts/deploy-smoke with /tower/deploy/smoke-token) or carried in last-build.fast_owned:
#    ok, not rolled back, and its digest the one the key names (artifacts/lambda/<function>/<digest>.zip). DEPLOY_FAST_STATUS_CMD
#    replaces the status read (a test).
port_fast_owned() {
  local stack since tagc fast wantp ok applied
  [[ -z "${bgood:-}" ]] || { echo "port: redeployed: a bisection deploys an older commit"; return 1; }
  stack="$(aws cloudformation describe-stacks --stack-name tower-app-port --query 'Stacks[0]' --output json 2>/dev/null)" \
    && jq -e 'type == "object"' <<<"$stack" >/dev/null 2>&1 || { echo "port: redeployed: tower-app-port is not readable"; return 1; }
  [[ "$(jq -r '.StackStatus' <<<"$stack")" =~ ^(CREATE|UPDATE)_COMPLETE$ ]] || { echo "port: redeployed: tower-app-port is $(jq -r '.StackStatus' <<<"$stack")"; return 1; }
  # STACK-COMMIT-OFF-TAGS: the template as last applied is last-build.port_tpl (its sha256, recorded at the apply); a stack an
  # older deployer applied still carries its commit tag, and the template is compared at that commit as before
  applied="$(jq -r '.port_tpl // empty' <<<"$prev_build" 2>/dev/null)"
  if [[ -n "$applied" ]]; then
    [[ "$applied" = "$(sha256sum <"${tpl[port]}" | cut -c1-20)" ]] || { echo "port: redeployed: its template is not the one last applied"; return 1; }
  else
    tagc="$(jq -r '[(.Tags // [])[] | select(.Key == "commit") | .Value][0] // empty' <<<"$stack")"
    if [[ -z "$tagc" ]] || ! git -C "$repo" cat-file -e "$tagc^{commit}" 2>/dev/null || ! git -C "$repo" diff --quiet "$tagc" "$head" -- "${tpl[port]#"$repo"/}" 2>/dev/null; then
      echo "port: redeployed: its template is not the one applied at ${tagc:-an unknown commit}"; return 1
    fi
  fi
  wantp="$(printf '%s\n' ${lambda_params[@]+"${lambda_params[@]}"} | jq -R 'select(length > 0) | capture("^(?<k>[^=]+)=(?<v>.*)$") | {(.k): .v}' | jq -sc add)"
  since="$(aws cloudformation describe-stack-events --stack-name tower-app-port --max-items 1 --query 'StackEvents[0].Timestamp' --output text 2>/dev/null | head -n 1)"
  since="$(date -u -d "$since" +%s 2>/dev/null)" || { echo "port: redeployed: the end of its last operation is unknown"; return 1; }
  fast="$(fast_status "$stack" | jq -c '.fast // [] | if type == "array" then . else [] end' 2>/dev/null)"; [[ -n "$fast" ]] || fast='[]'
  ok="$(jq -nc --argjson s "$stack" --argjson w "$wantp" --argjson fast "$fast" --argjson carry "$(jq -c '.fast_owned // {} | if type == "object" then . else {} end' <<<"$prev_build" 2>/dev/null || echo '{}')" --argjson since "$since" '
    (($s.Parameters // []) | map({(.ParameterKey): .ParameterValue}) | add // {}) as $p
    | if ($w | type) != "object" or $w.DepsKey != $p.DepsKey or $w.PortCode == null then {why: "the layer differs from the stack, or the lambda key is unknown"}
      else [{k: "PortCode", f: "tower-port-api"}
            | select($w[.k] != $p[.k]) | . as $x | ($w[$x.k] | (capture("/(?<d>[0-9a-f]{64})\\.zip$").d) // "") as $d
            | ([$fast[] | select(.function == $x.f and .ok != null and ((.at // 0) | tonumber? // 0) > $since)
                | {d: .digest, v: (.to_version // .version), at: (.at | tonumber), ok, rb: (.rolled_back == true)}]
               + [($carry[$x.f] // empty) | select(type == "object" and ((.at // 0) | tonumber? // 0) > $since) | . + {ok: true, rb: false}]
               | max_by(.at)) as $e
            | {f: $x.f, d: $d, e: $e}]
        | if length == 0 then {why: "no lambda key differs from the stack"}
          elif all(.d != "" and .e != null and .e.ok == true and (.e.rb | not) and .e.d == .d) then {owned: (map({(.f): {d, v: .e.v, at: .e.at}}) | add)}
          else {why: "no ok swap after its last update for \(map(select(.d == "" or .e == null or .e.ok != true or .e.rb or .e.d != .d) | .f) | join(", "))"} end end' 2>/dev/null)"
  if ! jq -e '.owned' <<<"$ok" >/dev/null 2>&1; then echo "port: redeployed: $(jq -r '.why // "the evidence is unreadable"' <<<"$ok" 2>/dev/null || echo 'the evidence is unreadable')"; return 1; fi
  jq -c .owned <<<"$ok" >"$work/fast_owned"
  echo "port: code live by the fast path ($(jq -r '.owned | to_entries | map("\(.key) v\(.value.v)") | join(", ")' <<<"$ok")), stack not redeployed (it keeps the older keys; the next real port deploy passes the current ones)"
}

# fast_status <stack json>: the port's GET /v1/deploy/status, authenticated as scripts/deploy-smoke does (DEPLOY_SMOKE_TOKEN or the
# SecureString /tower/deploy/smoke-token, inside the /tower/deploy/* read the deployer has; the URL is the stack's PortUrl). No token
# or no answer: nothing (then no swap is known and the port stack is deployed). The token goes to curl on stdin, never in argv or the log.
# STATUS-HOLD (D-331): with STATUS_HOLD_S (and STATUS_SEEN) in its environment, the read is the port's long poll (port.long_poll,
# ?wait_s=N&seen=D): held until the status is not the answer D names or N s pass; DEPLOY_FAST_STATUS_CMD sees the two variables.
fast_status() {
  local url token query="" hold="${STATUS_HOLD_S:-0}"
  if [[ -n "${DEPLOY_FAST_STATUS_CMD:-}" ]]; then bash -c "$DEPLOY_FAST_STATUS_CMD"; return; fi
  url="$(jq -r '[(.Outputs // [])[] | select(.OutputKey == "PortUrl") | .OutputValue][0] // empty' <<<"$1")"
  token="${DEPLOY_SMOKE_TOKEN:-}"
  [[ -n "$token" ]] || token="$(aws ssm get-parameter --name /tower/deploy/smoke-token --with-decryption --query Parameter.Value --output text 2>/dev/null)" || token=""
  [[ -n "$url" && -n "$token" && "$token" != None ]] || return 1
  [[ "$hold" =~ ^[0-9]+$ ]] || hold=0
  (( hold > 0 )) && query="?wait_s=$hold${STATUS_SEEN:+&seen=$STATUS_SEEN}"
  curl -sS -m $(( hold + 10 )) -K - "${url%/}/v1/deploy/status$query" 2>/dev/null <<<"header = \"Authorization: Bearer $token\""
}

# STATUS-HOLD (D-331: a wait on a state is an event, never a read on an interval): status_wait <stack json> <seen> [<hold s>] [<file>]:
# the port's GET /v1/deploy/status held as a long poll (port.long_poll, PORT-LONG-POLL) on the LISTEN of tower_status, which
# every platform.deploy.* event wakes (migration 0023): a stack's end (the EventBridge rule tower-app-stack-state ->
# platform.deploy.ended, source cloudformation, the status's stacks), a new task's up (task_up), a reload's step (image_reload),
# the migrations the live service applied (migrated). It answers at once when the status is not the one <seen> names (none:
# at once), else at the first event that changed it, or after <hold> s (STATUS_HOLD_S_MAX, the port's canary.WAIT_MAX_S, at most:
# a lost event costs that bound, never a verdict). Writes the answer to <file> ($work/status.json) and echoes its seen; 1 (and an
# empty <file>) when the status cannot be read or comes unmarked (a port older than PORT-LONG-POLL: there is nothing to wait on).
STATUS_HOLD_S_MAX=20
status_wait() {
  local said hold="${3:-$STATUS_HOLD_S_MAX}" out="${4:-$work/status.json}"
  [[ "$hold" =~ ^[0-9]+$ ]] || hold=$STATUS_HOLD_S_MAX
  (( hold < 1 )) && hold=1; (( hold > STATUS_HOLD_S_MAX )) && hold=$STATUS_HOLD_S_MAX
  said="$(STATUS_HOLD_S="$hold" STATUS_SEEN="${2:-}" fast_status "$1" 2>/dev/null)" || said=""
  if ! jq -e '.long_poll.seen | strings | test("^[0-9a-f]{8,64}$")' <<<"$said" >/dev/null 2>&1; then : >"$out"; return 1; fi
  printf '%s\n' "$said" >"$out"
  jq -r '.long_poll.seen' <<<"$said"
}

# STACK-END-BY-EVENT (D-331): stack_event <name> <status> [<seen>]: waits for the next event that may end tower-app-<name>'s
# operation and echoes the long poll's seen, for the caller to read the stack's status again. A stack of the home region:
# CloudFormation's Stack Status Change of its end reaches the port (the bootstrap's EventBridge rule tower-app-stack-state ->
# http_port.stack_state: platform.deploy.ended, source cloudformation, the status's stacks), as does the up of a rollout's new
# task (platform.deploy.task_up), and each wakes the port's long poll, so the status is held (status_wait) until one of them, or
# STATUS_HOLD_S_MAX at most (a lost event costs that bound). A stack of another region (MEDIA-REPLICA: the rule is the home
# region's), or a status the port does not hold (no token, a port older than PORT-LONG-POLL): CloudFormation's own waiter for the
# operation <status> names, once (its fixed 30 s is the net's, not the event path's); any exit of it is only a cue to read again.
stack_event() {
  local n="$1" status="$2" seen="${3:-}" waiter
  if [[ -z "${at_region[$n]:-}" ]] && seen="$(status_wait "$(port_stack)" "$seen" "" "$work/stack_event.$n")"; then
    printf '%s' "$seen"; return 0
  fi
  case "$status" in
    CREATE_*|ROLLBACK_*) waiter=stack-create-complete ;;  # ROLLBACK_COMPLETE is one of its failures: the create's end
    DELETE_*) waiter=stack-delete-complete ;;
    IMPORT_*) waiter=stack-import-complete ;;
    *) waiter=stack-update-complete ;;  # UPDATE_ROLLBACK_COMPLETE and UPDATE_*_FAILED are its failures: the update's end
  esac
  aws cloudformation wait "$waiter" ${at_region[$n]:+--region "${at_region[$n]}"} --stack-name "tower-app-$n" >/dev/null 2>&1 || :
}

# port_stack: the tower-app-port stack (its PortUrl), read once per build into $work/port_stack.json; nothing when unreadable.
port_stack() {
  if [[ ! -s "$work/port_stack.json" ]]; then
    aws cloudformation describe-stacks --stack-name tower-app-port --query 'Stacks[0]' --output json >"$work/port_stack.json.$BASHPID" 2>/dev/null \
      && mv "$work/port_stack.json.$BASHPID" "$work/port_stack.json"
    rm -f "$work/port_stack.json.$BASHPID"
  fi
  slurp "$work/port_stack.json"
}

# SLOW-PATH-NO-ROLLOUT-WAIT: code_live: 0 when this batch is a code-only landing whose code is ALREADY LIVE AND DURABLE, so nothing
# of the image, the service stack or the runner stack is deployed: no image build (82 s), no ECS rollout (5 to 9 minutes each).
# Like the port of DEP7-PORT-FAST-OWNED it is verified by digest and every unknown deploys, as before. All of:
#  - the batch (the classifier's answer): its only slow target is the service image, no manual target, and every path with that
#    target is under infra/service/tower_infra/ (deploy_classify.code_only: what a code bundle carries; a Dockerfile,
#    requirements.txt, a migration or a template is a real change);
#  - the head's code bundle (lambda_package.py code, nothing uploaded) has the sha256 deploy.live_code names (the status's
#    live_code, '<sha256>@<merge>', which the live service wrote after the landing's swap): the head's code IS that bundle;
#  - every ECS task runs it: a platform.deploy.image_reload {state: reloaded} of that digest by each role that has one
#    (IMAGE-SWAP-RELOAD: the ECS task loaded the bundle in place and took the role back);
#  - a task ECS starts later boots it (code_bundle.boot): each of those roles' stacks is *_COMPLETE and either its LiveCode is
#    that digest or its LiveSeen is neither the datum nor `unknown`; and they carry the same LiveCode.
# CODE-LIVE-ROLES-THAT-EXIST (GATE-SHUTDOWN, D-314): the roles are the stacks of service and runner whose template carries an
# AWS::ECS::Service (ecs_roles). The runner's ECS service is gone (tower-app-runner is the outputs bucket alone), so no runner
# task reloads anything: asking for "runner service" made every code-only landing fail this check for ever.
# Then: $work/code_live = the digest (last-build.code_live), no image, no service, no runner among the targets (port keeps its own
# rule), and the two stacks keep the LiveCode they have ($work/livecode_keep: their hash is the recorded one, nothing is dirty).
# DEPLOY_CODE_DIGEST_CMD replaces the digest's command (a test).
# CODE-LIVE-RELATIVE-ROOT: the reason a code-only batch was not skipped, said in the log and kept in last-build.code_live_why
# (the log's tail in the record is too short to hold it: on 11/11 the reason of #496 could not be read from the status)
code_live_no() { echo "code live: no: $1"; printf '%s' "$1" | cut -c1-300 >"$work/code_live_why"; }
# ecs_roles: the names among service and runner whose stack template (infra/aws/stacks/NN-<name>.json at this tree) carries an
# AWS::ECS::Service, in that order, space-separated: the roles that have ECS tasks to run the code.
ecs_roles() {
  local n f out=""
  for n in service runner; do
    for f in "$repo"/infra/aws/stacks/[0-9]*-"$n".json; do
      [[ -f "$f" ]] && grep -q '"AWS::ECS::Service"' "$f" && out="$out $n"
    done
  done
  printf '%s' "${out# }"
}
# code_live_stacks <digest> <datum> <roles>: a task ECS starts in the stack of each role would boot <digest> while
# deploy.live_code is <datum>: the stack is *_COMPLETE and its LiveCode is the digest, or its LiveSeen is neither the datum
# nor `unknown`; and they carry the same LiveCode. Prints "=<that LiveCode>"; else says why (code_live_no) and returns 1.
code_live_stacks() {
  local n stack code keep=""
  for n in $3; do
    stack="$(aws cloudformation describe-stacks --stack-name "tower-app-$n" --query 'Stacks[0]' --output json 2>/dev/null)" || stack=""
    code="$(jq -r --arg d "$1" --arg m "$2" '
      (((.Parameters // []) | map({(.ParameterKey): .ParameterValue}) | add) // {}) as $p
      | select((.StackStatus | test("^(CREATE|UPDATE)_COMPLETE$"))
               and (($p.LiveCode // "") == $d or (($p.LiveSeen // "unknown") as $s | $s != "unknown" and $s != $m)))
      | "=" + ($p.LiveCode // "")' <<<"$stack" 2>/dev/null)"
    [[ -n "$code" ]] || { code_live_no "a task ECS starts in tower-app-$n would not boot ${1:0:12} (the stack is not complete, or its task definition does not follow the live code)" >&2; return 1; }
    [[ -z "$keep" || "$keep" = "$code" ]] || { code_live_no "the stacks of $3 carry different LiveCode" >&2; return 1; }
    keep="$code"
  done
  printf '%s' "$keep"
}
# HEAD-CODE-LIVE (the Torre, 15/11: #40's build, 4 min 39 s for a change of scripts/): code_live head is the same proof for a
# batch with no image and no stack of the ECS tasks among its targets (scripts, docs, a Lambda's swap, the port stack). After
# a run of code-only merges kept the two stacks (livecode_keep), such a build found them "dirty": live_code moved their
# LiveCode to the newest swap's bundle, the stack's hash with it, and the ECS service rolled out (3 min 24 s) onto code it
# already ran. When the head's code bundle is deploy.live_code's, reloaded by every ECS task and booted by any task ECS starts
# (the checks below), the stacks keep what they have here too; anything else is as before.
code_live() {
  local digest datum roles n keep="" want_roles
  [[ -z "${bgood:-}" && -z "${DEPLOY_TARGETS:-}" && -s "$work/classify.json" ]] || return 1
  if [[ "${1:-}" = head ]]; then
    jq -e '((.slow // []) | map(select(. == "slow:service-image" or . == "slow:stack-service" or . == "slow:stack-runner"
           or . == "slow:stack-all")) | length == 0)' "$work/classify.json" >/dev/null 2>&1 || return 1
  else
  # CODE-BESIDE-PORT: the port stack may change beside the code (deploy_classify.BESIDE): it stays this build's target
  # OWNER-STEP-NEEDS-ROLLOUT: the owner's step (dbinit.py) runs from the image (deploy_classify.IMAGE_RUN): not code-only
  # SUPERVISOR-NEEDS-ROLLOUT: and so does the task's supervisor (supervisor.py), for the task's whole life
  # RESTORE-DRILL: and the reading of a restored database (restore_check.py), the init container's command
  # TASK-POOLER: and the task's pool of connections (pooler.py), a process of the image for the task's whole life
  jq -e '((.slow // []) | index("slow:service-image") != null) and (((.slow // []) - ["slow:service-image", "slow:stack-port"]) | length == 0)
         and ((.manual // []) | length == 0)
         and ([.paths[] | select(.targets | index("slow:service-image")) | .path
               | (startswith("infra/service/tower_infra/") and . != "infra/service/tower_infra/dbinit.py"
                  and . != "infra/service/tower_infra/supervisor.py"
                  and . != "infra/service/tower_infra/restore_check.py"
                  and . != "infra/service/tower_infra/pooler.py")] | all)' \
    "$work/classify.json" >/dev/null 2>&1 || return 1
  fi
  # CODE-LIVE-RELATIVE-ROOT: --root is `.` because this runs inside $repo, which is the relative `repo` in the real build: with
  # `--root $repo` the bundle was looked for in repo/repo, the digest was always "unknown" and no code-only landing was ever skipped
  digest="$(cd "$repo" && TOWER_ARTIFACT_BUCKET= bash -c "${DEPLOY_CODE_DIGEST_CMD:-python3 $ctl/scripts/lib/lambda_package.py code --root .}" 2>/dev/null \
    | grep '^{' | tail -n 1 | jq -r '.sha256 // empty' 2>/dev/null)"
  [[ "$digest" =~ ^[0-9a-f]{64}$ ]] || { code_live_no "the digest of the head's code bundle is unknown"; return 1; }
  echo "$digest" >"$work/code_digest"  # FAST-PATH-RELOAD: a code-only batch whose bundle is known: reload_live may ask for it
  deploy_status
  datum="$(jq -r '.live_code // empty' "$work/status.json" 2>/dev/null)"
  [[ "${datum%%@*}" = "$digest" ]] || { code_live_no "deploy.live_code is ${datum:-not readable}, the head's code is ${digest:0:12}"; return 1; }
  want_roles="$(ecs_roles)"
  [[ -n "$want_roles" ]] || { code_live_no "no stack of service or runner carries an ECS service"; return 1; }
  roles="$(jq -r --arg d "$digest" '[(.image_reload // [])[] | select(type == "object" and .digest == $d and .state == "reloaded") | .role] | unique | join(" ")' "$work/status.json" 2>/dev/null)"
  for n in $want_roles; do
    [[ " $roles " == *" $n "* ]] || { code_live_no "${digest:0:12} was not reloaded in place by the ECS task of every role ($want_roles; reloaded: ${roles:-none})"; return 1; }
  done
  keep="$(code_live_stacks "$digest" "$datum" "$want_roles")" || return 1
  echo "$digest" >"$work/code_live"; printf '%s' "${keep#=}" >"$work/livecode_keep"  # (empty stays an empty file: no LiveCode in the hash)
  grep -v -x -e service -e runner "$work/targets" >"$work/targets.tmp"; mv "$work/targets.tmp" "$work/targets"; echo 0 >"$work/image"
  jq -R 'select(length > 0)' "$work/targets" | jq -sc . >"$work/targets_json"
  echo "code live: yes${1:+ ($1)}: the head's code is the bundle ${digest:0:12} of deploy.live_code, reloaded in place by the ECS task of $want_roles and booted by any task ECS starts: no image is built, the service and runner stacks are left alone"
}

# FAST-PATH-RELOAD (GATE-SHUTDOWN, D-314; the Torre accepted the design of PR #23, 14/11): a code-only batch whose bundle is not
# yet deploy.live_code is put live IN PLACE, by the live service, in this build. On GitHub no landing orders the reload any more
# (the service's autodeploy ordered it from Origin's landings) and no runner exists to judge it, so:
#  1. the head's bundle is published (lambda_package.py code, as migrate_ask) and named in last-build.reload {key, sha256, head,
#     state: asked}, written at once (progress); the service's autodeploy look, which heard this build start (its CodeBuild
#     event) and reads last-build every 2 s meanwhile, orders the service alone to load it (autodeploy.build_reload);
#  2. the service drains, execs the bundle, says reloaded at its first good tick and proven after its own good ticks
#     (live_image.PROVE_*); its autodeploy then writes deploy.live_code = <sha256>@<head>;
#  3. this build reads the port's GET /v1/deploy/status as the order's records arrive, held on its long poll (STATUS-HOLD,
#     status_wait: each record wakes it; an answer the port does not hold ends the wait as `unheld`, never a pause): done
#     when live_code is the head's bundle; given up at once when the service says the reload failed or declined it; and
#     DEPLOY_RELOAD_WAIT_S (default 150) only bounds that wait, and DEPLOY_RELOAD_ORDER_S (default 30) the wait for the order
#     itself (a live service of an older code, or one that did not hear the build start, orders nothing). Then code_live is
#     asked again: yes, no image and no ECS
#     stack, and the smoke runs (smoke: $work/reloaded). Any other outcome: the image path, in this same build, as before:
#     the build is green only if that succeeds. last-build.reload keeps the outcome {state: live|failed|declined|timeout|
#     unordered|unheld|unproven, s: the ask to the verdict, reloaded/proven: what the service said}.
# Not in a bisection or with DEPLOY_TARGETS (code_live's own rule), not when a reload onto the bundle failed before, nor when the
# service stack would not boot the bundle once it is the datum; DEPLOY_RELOAD_WAIT_S=0 turns it off. DEPLOY_CODE_BUNDLE_CMD
# replaces the publish (a test), as for migrate_ask.
reload_states() {  # what the status says of this head's order and of this bundle, as one line: "<state>[ <why>]" per row
  jq -r --arg d "$1" --arg h "$2" --argjson t "$3" '[(.image_reload // [])[] | select(type == "object" and .digest == $d
      and ((.order // .head // "") == $h or .state == "failed") and ((.at // 0) | tonumber? // 0) >= $t - 30)]
    | sort_by(.at // 0)[] | "\(.state)\(if .why then " " + (.why | tostring | .[0:200]) else "" end)"' "$work/status.json" 2>/dev/null
}
reload_live() {
  local digest limit out asked deadline datum seen="" said="" state="" why="" t s port_stack held="" hold order_limit="${DEPLOY_RELOAD_ORDER_S:-30}"
  digest="$(slurp "$work/code_digest")"
  [[ "$digest" =~ ^[0-9a-f]{64}$ && -z "${bgood:-}" && -z "${DEPLOY_TARGETS:-}" ]] || return 1
  limit="${DEPLOY_RELOAD_WAIT_S:-150}"
  [[ "$limit" =~ ^[0-9]+$ ]] && (( limit > 0 )) || { echo "reload: off (DEPLOY_RELOAD_WAIT_S=$limit)"; return 1; }
  [[ "$(ecs_roles)" = service ]] || { echo "reload: in place is for the service alone, and the roles with an ECS service are: $(ecs_roles)"; return 1; }
  if jq -e --arg d "$digest" '[(.image_reload // [])[] | select(type == "object" and .digest == $d and .state == "failed")] | length > 0' \
      "$work/status.json" >/dev/null 2>&1; then
    echo "reload: a reload onto ${digest:0:12} failed before: the image path"; return 1
  fi
  code_live_stacks "$digest" "$digest@$head" service >/dev/null || { echo "reload: not asked: the service stack would not boot it"; return 1; }
  out="$(TOWER_ARTIFACT_BUCKET="$lambda_bucket" timeout 120 bash -c "${DEPLOY_CODE_BUNDLE_CMD:-python3 $ctl/scripts/lib/lambda_package.py code --root $repo}" 2>&1 | grep '^{' | tail -n 1)"
  if ! jq -e --arg d "$digest" '.sha256 == $d and (.key | test("^artifacts/lambda/tower-code/[0-9a-f]{64}\\.zip$"))' <<<"$out" >/dev/null 2>&1; then
    echo "reload: the head's code bundle ${digest:0:12} was not published: the image path"; return 1
  fi
  asked="$EPOCHSECONDS"; deadline=$((asked + limit))
  jq -c --arg h "$head" --argjson t "$asked" '{key, sha256, head: $h, state: "asked", at: $t}' <<<"$out" >"$work/reload"
  echo "reload: asked the live service to load ${digest:0:12} in place (last-build.reload); waiting for deploy.live_code=${digest:0:12}@${head:0:10} (${limit}s at most)"
  progress  # the ask is the live service's to read now
  port_stack="$(port_stack)"
  while :; do
    # STATUS-HOLD (D-331): the status held until the service's next word on the order (an image_reload step, deploy.live_code:
    # both platform.deploy.* events that wake the long poll), never read on an interval; within the deadline and, while the
    # service said nothing of it, within the order's limit
    hold=$(( deadline - EPOCHSECONDS ))
    [[ -z "$said" ]] && (( asked + order_limit - EPOCHSECONDS < hold )) && hold=$(( asked + order_limit - EPOCHSECONDS ))
    if ! held="$(status_wait "$port_stack" "$held" "$hold")"; then
      state=unheld; why="the status could not be held (the port unreadable, or older than PORT-LONG-POLL)"; break
    fi
    datum="$(jq -r '.live_code // empty' "$work/status.json" 2>/dev/null)"
    said="$(reload_states "$digest" "$head" "$asked")"
    [[ -n "$said" && "$said" != "$seen" ]] && { echo "reload: the service says: $(printf '%s' "$said" | cut -d' ' -f1 | tr '\n' ' ')"; seen="$said"; }
    if [[ "$datum" = "$digest@$head" ]]; then state=live; break; fi
    t="$(grep -m 1 -E '^(failed|declined)' <<<"$said")"
    if [[ -n "$t" ]]; then state="${t%% *}"; why="${t#* }"; [[ "$why" = "$t" ]] && why=""; break; fi
    (( $EPOCHSECONDS < deadline )) || { state=timeout; break; }
    if [[ -z "$said" ]] && (( $EPOCHSECONDS - asked >= order_limit )); then state=unordered; why="no order of it in ${order_limit}s"; break; fi
  done
  s=$(( $EPOCHSECONDS - asked ))
  if [[ "$state" = live ]] && code_live; then
    rm -f "${work:?}/code_live_why"; echo "$s" >"$work/reloaded"
    echo "reload: live in ${s}s: the service runs ${digest:0:12} in place and proved it; deploy.live_code names it"
  else
    [[ "$state" = live ]] && { state=unproven; why="$(slurp "$work/code_live_why")"; }
    echo "reload: $state after ${s}s${why:+: $why}: the image path, in this build"
    code_live_no "the reload in place was $state after ${s}s${why:+: $why}" >/dev/null
  fi
  t="$(jq -c --arg d "$digest" --arg h "$head" \
      '[(.image_reload // [])[] | select(type == "object" and .digest == $d and (.order // "") == $h and (.state == "reloaded" or .state == "proven"))]
       | map({(.state): ({reload_s, boot_s, ticks, window_s, order_s} | with_entries(select(.value != null)))}) | add // {}' "$work/status.json" 2>/dev/null)" || t=""
  jq -c --arg st "$state" --argjson s "$s" --arg w "$why" --argjson said "${t:-{\}}" \
    '. + {state: $st, s: $s} + (if $w != "" then {why: ($w | .[0:200])} else {} end) + $said' "$work/reload" >"$work/reload.tmp" \
    && mv "$work/reload.tmp" "$work/reload"
  [[ "$state" = live ]]
}

# IMAGE-STAGE-CACHE: stage_cache <dockerfile> <repository>: the cache of the image's earlier build stages, in stage_from (the
# --cache-from arguments). The previous image (/tower/deploy/image/<name>) is the cache of the FINAL stage only: an inline cache
# (BUILDKIT_INLINE_CACHE) and the classic builder's history both hold the layers of the image, and an earlier stage's are not in
# it. So the service's `clis` stage (npm install of the two subscription CLIs) ran again at every build, and everything after its
# COPY --from with it: tower-infra-deploy:41c163b1 (14/11, #22) spent 73 s on image:service for a change of tower_infra alone.
# Each named stage that is not the last one and reads nothing of the build context (only COPY --from=, no ADD) is kept as its
# own image, tower-<name>:stage-<stage>-<sha256 of the Dockerfile up to its end, comments and blank lines left out>: content-
# addressed, so a tag that exists is that stage, pulled and given as cache; a missing one is built (--target, inline cache) and
# pushed once, and the image's own build then finds it in the local cache. It names no new IAM action (the deployer pushes and
# describes tower-<name> already) and the repository's lifecycle (10 images) expires it like any image: rebuilt once then.
# Never fails a build: a stage that cannot be pulled or kept is built inside the image, as before.
stage_cache() {
  local dockerfile="$1" repository="$2" stage text tag ref total
  stage_from=()
  total="$(grep -c -i -E '^[[:space:]]*FROM[[:space:]]' "$dockerfile")"
  while read -r stage; do
    [[ -n "$stage" ]] || continue
    text="$(grep -v -E '^[[:space:]]*(#|$)' "$dockerfile" | awk -v s="$stage" \
      'toupper($1) == "FROM" { if (seen) exit; if (tolower($NF) == tolower(s) && toupper($(NF-1)) == "AS") seen = 1 } { print }')"
    (( $(grep -c -i -E '^[[:space:]]*FROM[[:space:]]' <<<"$text") < total )) || continue  # the last stage is the image itself
    if grep -i -E '^[[:space:]]*(COPY|ADD)[[:space:]]' <<<"$text" | grep -q -v -i -E '^[[:space:]]*COPY[[:space:]].*--from='; then
      echo "image cache: stage $stage reads the build context: built in the image"; continue
    fi
    tag="stage-$stage-$(printf '%s\n' "$text" | sha256sum | cut -c1-20)"; ref="$IMAGE_REGISTRY/$repository:$tag"
    if aws ecr describe-images --repository-name "$repository" --image-ids imageTag="$tag" >/dev/null 2>&1; then
      if docker pull --quiet "$ref" >/dev/null 2>&1; then stage_from+=(--cache-from "$ref"); echo "image cache: stage $stage from $ref"
      else echo "image cache: stage $stage: $ref could not be pulled: built in the image"; fi
    elif docker build --quiet --target "$stage" --build-arg BUILDKIT_INLINE_CACHE=1 --file "$dockerfile" --tag "$ref" "$repo" >/dev/null \
        && docker push --quiet "$ref" >/dev/null; then
      stage_from+=(--cache-from "$ref"); echo "image cache: stage $stage built and kept as $ref"
    else
      echo "image cache: stage $stage could not be kept: built in the image"
    fi
  done < <(sed -n -E 's/^[[:space:]]*[Ff][Rr][Oo][Mm][[:space:]]+.*[[:space:]][Aa][Ss][[:space:]]+([A-Za-z0-9_.-]+)[[:space:]]*$/\1/p' "$dockerfile")
}

# deploy_status: the port's GET /v1/deploy/status, read once per build into $work/status.json (empty when it cannot be read).
deploy_status() {
  [[ -f "$work/status.json" ]] && return 0
  fast_status "$(aws cloudformation describe-stacks --stack-name tower-app-port --query 'Stacks[0]' --output json 2>/dev/null)" >"$work/status.json" 2>/dev/null || : >"$work/status.json"
}

# VERIFY-AT-UP: up_seen <name> <t0> <image>: the earliest time a task of tower-app-<name> said it is up (platform.deploy.task_up,
# the port's GET /v1/deploy/status task_up, read afresh at each call) on <image>, since <t0> (less 30 s of clocks); nothing when
# none did or the status cannot be read (the stack's end is then waited, as before). The deployer reads ECS through the port:
# its role has no ecs:Describe*, and needs none for this
up_seen() {
  fast_status "$(port_stack)" 2>/dev/null | jq -r --arg s "tower-app-$1" --argjson t0 "$2" --arg i "$3" \
    '[(.task_up // [])[] | select(type == "object" and .stack == $s and .image == $i and ((.at // 0) >= $t0 - 30)) | .at] | min // empty' 2>/dev/null
}

# IMAGE-PREWARM-C: live_code: the LiveCode of the service and runner stacks (their tasks boot that code bundle and carry it as
# TOWER_IMAGE_DIGEST, so they work beside the standbys a landing promoted, under the same pointer). The newest swap of the
# status's image_swap (the autodeploy's) names the bundle S and the merge it promoted; S is the head's code when no commit
# since that merge touched the bundle's inputs (lambda_package.CODE_INPUTS). Else, or with no status: empty, the image's own
# code. Writes $work/livecode.
# SLOW-PATH-NO-ROLLOUT-WAIT: and their LiveSeen ($work/liveseen): deploy.live_code as the status has it now ('<sha256>@<merge>'
# or empty), the stamp of the task definitions this build deploys: a task of theirs boots the live code only when the datum
# is another value by then, i.e. a landing swapped after this deploy (code_bundle.boot). `unknown` when the status cannot be
# read or does not carry it: those task definitions never follow the datum. It is not in the stacks' hash.
code_inputs="infra/service/tower_infra infra/db/migrations infra/service/requirements.txt"
live_code() {
  local swap d h seen refused
  : >"$work/livecode"
  deploy_status
  seen="$(jq -r 'if has("live_code") then (.live_code // "") else "unknown" end' "$work/status.json" 2>/dev/null)" || seen=unknown
  [[ "$seen" =~ ^(unknown|[0-9a-f]{64}@[0-9a-f]{7,64})?$ && -s "$work/status.json" ]] || seen=unknown
  echo "$seen" >"$work/liveseen"
  if [[ -f "$work/code_live" ]]; then  # SLOW-PATH-NO-ROLLOUT-WAIT: code_live: the two stacks are not deployed and keep what they have
    cat "$work/livecode_keep" >"$work/livecode"
    echo "live code: live by deploy.live_code ($(cut -c1-12 "$work/code_live")): the stacks keep LiveCode=$(cut -c1-12 "$work/livecode")"
    return 0
  fi
  swap="$(jq -c '[(.image_swap // [])[] | select(type == "object" and .swapped == true)][0] // empty' "$work/status.json" 2>/dev/null)" || swap=""
  d="$(jq -r '.digest // empty' <<<"$swap" 2>/dev/null)"; h="$(jq -r '.head // empty' <<<"$swap" 2>/dev/null)"
  # LIVECODE-NOT-REFUSED: a bundle the engine refused (its swap's canary was red: image_retired by canary; or a reload onto it
  # failed) is not given to the stacks, whatever the head: a task that boots it would run what the canary judged broken
  refused="$(jq -r --arg d "$d" '[((.image_retired // [])[] | select(type == "object" and .digest == $d and .by == "canary")),
      ((.image_reload // [])[] | select(type == "object" and .digest == $d and .state == "failed"))] | length' "$work/status.json" 2>/dev/null)" || refused=0
  if [[ "$d" =~ ^[0-9a-f]{64}$ && "${refused:-0}" != 0 ]]; then
    echo "live code: the bundle ${d:0:12} swapped at ${h:0:10} was refused by the engine (a red canary or a failed reload)"
    echo "live code: none: the tasks run the code of their image"
  elif [[ "$d" =~ ^[0-9a-f]{64}$ ]] && git -C "$repo" cat-file -e "$h^{commit}" 2>/dev/null \
      && git -C "$repo" diff --quiet "$h" "$head" -- $code_inputs 2>/dev/null; then
    echo "$d" >"$work/livecode"; echo "live code: LiveCode=${d:0:12} (the bundle swapped at ${h:0:10} is this head's code)"
  else
    [[ -n "$d" ]] && echo "live code: the bundle ${d:0:12} swapped at ${h:0:10} is not the code of this head"
    echo "live code: none: the tasks run the code of their image"
  fi
}

# SLOW-PATH-NO-ROLLOUT-WAIT: the migrations of the head are applied by the LIVE service before any stack starts, so a new runner
# never meets an old schema and its rollout does not wait for the service's (on 10/11 a migration made a 981 s cycle: 312 s of the
# service, then 523 s of the runner). migrate_ask (right after the classification, so the image build covers the service's look):
# when infra/db changed in last-sha..head, publish the head's code bundle (lambda_package.py code: tower_infra, the migrations,
# requirements.txt, by sha256 under artifacts/lambda/tower-code/) and name it in last-build.migrate {key, sha256, want: the newest
# migration}; the service's autodeploy look reads last-build (which only the deployer writes), checks the sha256 and applies what is
# missing. migrate_wait (before the stacks): GET /v1/health?migration (no token) says the newest migration applied; at `want` the
# edge to the service is waived ($work/migrated). No answer in DEPLOY_MIGRATE_WAIT_S (default 90: an older service, no port), a
# bisection, an unknown last-sha, or a changed migration with a line `-- deploy: not-additive`: the old order, the new service
# applies them at its boot and the runner waits for it. Migrations are additive (the tasks of the last deploy run on the new schema
# while the new ones start, as the runner already did); a breaking one is two deliveries, expand then contract.
# DEPLOY_CODE_BUNDLE_CMD replaces the publish and DEPLOY_MIGRATED_CMD the read (a test).
migrate_ask() {
  local out want marked
  [[ -z "${bgood:-}" && "$last" != none ]] && git -C "$repo" cat-file -e "$last^{commit}" 2>/dev/null || return 0
  git -C "$repo" diff --quiet "$last" "$head" -- infra/db 2>/dev/null && return 0
  want="$(cd "$repo" && ls infra/db/migrations/*.sql 2>/dev/null | sort | tail -n 1)"; want="$(basename "${want:-}" .sql)"
  [[ -n "$want" ]] || return 0
  marked="$(cd "$repo" && git diff --name-only "$last" "$head" -- infra/db | xargs -r grep -l -- '^-- deploy: not-additive' 2>/dev/null | head -n 1)"
  if [[ -n "$marked" ]]; then echo "migrate: $marked is marked not-additive: the new service applies it at its boot, the runner waits for the service"; return 0; fi
  step_begin migrate-ask
  out="$(TOWER_ARTIFACT_BUCKET="$lambda_bucket" timeout 120 bash -c "${DEPLOY_CODE_BUNDLE_CMD:-python3 $ctl/scripts/lib/lambda_package.py code --root $repo}" 2>&1 | grep '^{' | tail -n 1)"
  if jq -e '(.key | test("^artifacts/lambda/tower-code/[0-9a-f]{64}\\.zip$")) and (.sha256 | test("^[0-9a-f]{64}$"))' <<<"$out" >/dev/null 2>&1; then
    jq -c --arg w "$want" '{key, sha256, want: $w}' <<<"$out" >"$work/migrate"
    echo "migrate: asked the live service for the migrations of ${head:0:10} up to $want (bundle $(jq -r '.sha256[0:12]' <<<"$out"))"
  else
    echo "migrate: the head's code bundle was not published: the new service applies the migrations at its boot, the runner waits for the service"
  fi
  step_end migrate-ask 0
  if [[ -s "$work/migrate" ]]; then progress; fi  # PROGRESS-AT-START: the ask is the live service's to read now, not at the next step
}
# migrated: the newest migration the database has applied, as the port answers it; nothing when it cannot be read.
migrated() {
  local url
  if [[ -n "${DEPLOY_MIGRATED_CMD:-}" ]]; then bash -c "$DEPLOY_MIGRATED_CMD"; return; fi
  url="${DEPLOY_SMOKE_URL:-$(aws cloudformation describe-stacks --stack-name tower-app-port --query 'Stacks[0].Outputs[?OutputKey==`PortUrl`].OutputValue | [0]' --output text 2>/dev/null)}"
  [[ -n "$url" && "$url" != None ]] || return 1
  curl -sS -m 10 "${url%/}/v1/health?migration=1" 2>/dev/null | jq -r '.migration // empty' 2>/dev/null
}
# MIGRATED-EVENT (D-331): migrate_wait: the end of the live service's migrate() for this bundle (platform.deploy.migrated, the
# status's migrated: applied or failed) is waited on the status's long poll (status_wait: its insert wakes tower_status), never
# read on an interval, within DEPLOY_MIGRATE_WAIT_S; then the database is read once (migrated) and is the proof. A status the
# port does not hold (no token, a port older than PORT-LONG-POLL, or DEPLOY_FAST_STATUS_CMD in a test) ends the wait at once:
# the one read decides, and a database behind keeps the old order (the runner waits for the service), as a timeout does.
migrate_ended() {  # the state the status says this bundle's migrate() ended in (applied|failed), nothing while it has not
  jq -r --arg b "$1" '[(.migrated // [])[] | select(type == "object" and .bundle == $b) | .state | strings] | first // empty' \
    "$work/migrate_status.json" 2>/dev/null
}
migrate_wait() {
  local want got="" limit="${DEPLOY_MIGRATE_WAIT_S:-90}" deadline bundle held="" ended="" port_stack
  [[ -s "$work/migrate" ]] || return 0
  want="$(jq -r .want "$work/migrate")"; bundle="$(jq -r .sha256 "$work/migrate")"; deadline=$(( $EPOCHSECONDS + limit ))
  step_begin migrate
  port_stack="$(port_stack)"
  while (( $EPOCHSECONDS < deadline )) && held="$(status_wait "$port_stack" "$held" $(( deadline - EPOCHSECONDS )) "$work/migrate_status.json")"; do
    ended="$(migrate_ended "$bundle")"
    [[ -n "$ended" ]] && break
  done
  got="$(migrated)" || got=""
  [[ -n "$got" && ! "$got" < "$want" ]] && : >"$work/migrated"
  if [[ -f "$work/migrated" ]]; then echo "migrate: the live service applied the migrations (the database is at $got): the runner does not wait for the service"
  else
    [[ -n "$ended" ]] && ended=": the service says its migrate() $ended" || ended=" after ${limit}s"
    echo "migrate: $want is not applied$ended (the database is at ${got:-unknown}): the new service applies it at its boot, the runner waits for the service"; fi
  step_end migrate 0
}

# same_outputs <name>: SLOW-PATH-NO-ROLLOUT-WAIT: 0 when the stack's template exports at the head what it exported at last-sha: the
# file is unchanged, or both parse and their Outputs are equal. A local of deploy_stacks (tpl); anything unreadable is a change.
same_outputs() {
  local file="${tpl[$1]#"$repo"/}" was now
  git -C "$repo" diff --quiet "$last" "$head" -- "$file" 2>/dev/null && return 0
  was="$(git -C "$repo" show "$last:$file" 2>/dev/null | jq -cS '.Outputs // {}' 2>/dev/null)" || return 1
  now="$(jq -cS '.Outputs // {}' "${tpl[$1]}" 2>/dev/null)" || return 1
  [[ -n "$was" && "$was" = "$now" ]]
}

# SLOW-PATH-NO-ROLLOUT-WAIT, the helpers of deploy_stacks.
# changed_stacks: the stacks this build really changed (res/<n>.secs) or took over from the build that left them rolling (.settled):
# what the smoke is run for and what a red smoke rolls back.
changed_stacks() { ls "$work/res" 2>/dev/null | sed -n -E 's/\.(secs|settled)$//p' | sort -u; }
# failed_events <name> <since epoch>: the stack's FAILED events (ResourceStatusReason) for the build log, so GET /v1/deploy/status
# shows why: only the events of THIS operation (Timestamp >= its start: an old failure of the stack is not this one's), and the
# CLI's own error line, which is all there is when it fails before any event (change-set validation, exit 254/255 in seconds).
failed_events() {
  local since_iso; since_iso="$(date -u -d "@$2" +%Y-%m-%dT%H:%M:%S 2>/dev/null || echo 0000)"
  echo "failed events of tower-app-$1 (since $since_iso):"
  grep -E 'An error occurred|^(Error|Failed)|botocore|ValidationError' "$work/res/$1.log" 2>/dev/null | head -n 5 | cut -c1-400 | redact | sed 's/^/cli: /'
  aws cloudformation describe-stack-events ${at_region[$1]:+--region "${at_region[$1]}"} --stack-name "tower-app-$1" --output text \
    --query 'StackEvents[].[Timestamp,LogicalResourceId,ResourceStatus,ResourceStatusReason]' 2>&1 \
    | awk -F'\t' -v since="$since_iso" '$1 >= since' | grep '_FAILED' | head -n 12 | cut -c1-400 | redact
  echo
}
# SLOW-PATH-STACK-PARTS: slow_parts <name> <t0>: where a stack's real change spent its seconds, from its own events since <t0>:
# the four resources that took longest (first event to last, up to the stack's cleanup) and `cleanup` (from
# UPDATE_COMPLETE_CLEANUP_IN_PROGRESS to the stack's last event: the old resources' removal, which the CLI's deploy waits too).
# One JSON object {"<LogicalId>": seconds, ..., "cleanup": seconds}; nothing when the events cannot be read (the deployer already
# reads them: failed_events, port_fast_owned). Live 11/11: the port stack took 222 s for one property of its integration.
slow_parts() {
  aws cloudformation describe-stack-events ${at_region[$1]:+--region "${at_region[$1]}"} --stack-name "tower-app-$1" --max-items 300 --output json \
    --query 'StackEvents[].[Timestamp,LogicalResourceId,ResourceStatus]' 2>/dev/null \
    | jq -c --argjson t0 "$2" --arg stack "tower-app-$1" '
        [.[] | {at: (.[0] | sub("\\.[0-9]+"; "") | sub("\\+00:00$"; "Z") | fromdateiso8601), id: .[1], st: .[2]} | select(.at >= $t0 - 2)] as $e
        | ([$e[] | select(.id == $stack and .st == "UPDATE_COMPLETE_CLEANUP_IN_PROGRESS") | .at] | min) as $clean
        | ([$e[] | select(.id == $stack) | .at] | max) as $end
        | ([$e[] | select(.id != $stack and ($clean == null or .at <= $clean))] | group_by(.id)
           | map({key: .[0].id, value: ((map(.at) | max) - (map(.at) | min))}) | sort_by(-.value) | .[0:4] | from_entries)
          + (if $clean != null and $end != null then {cleanup: ($end - $clean)} else {} end)
        | select(length > 0)' 2>/dev/null
}
# rolled_out <name> <t0>: a rollout the earlier build started at <t0> is complete: its seconds, to the stack's newest event
# (res/<n>.roll, the end in .rollend); nothing when the event cannot be read.
rolled_out() {
  local end
  end="$(aws cloudformation describe-stack-events ${at_region[$1]:+--region "${at_region[$1]}"} --stack-name "tower-app-$1" --max-items 1 --query 'StackEvents[0].Timestamp' --output text 2>/dev/null | head -n 1)"
  end="$(date -u -d "$end" +%s 2>/dev/null)" || return 0
  (( end >= $2 )) || return 0
  echo "$(( end - $2 ))" >"$work/res/$1.roll"; echo "$end" >"$work/res/$1.rollend"
}
# LIVECODE-NOT-REFUSED: prev_params: what the service and runner stacks carry before this build touches them (LiveCode,
# LiveSeen), for the rollback: `aws cloudformation deploy` keeps a parameter it is not given, so a rollback with no
# overrides left the stacks with the LiveCode of the deploy it undid, and the tasks came up again on that bundle. A stack
# that does not exist yet, or cannot be read, has none: its rollback is as before. After live_code, before the stacks.
prev_params() {
  local n stack
  for n in service runner; do
    [[ -f "$work/prev_param.$n" ]] && continue  # carried from the build that left it rolling
    stack="$(aws cloudformation describe-stacks --stack-name "tower-app-$n" --query 'Stacks[0]' --output json 2>/dev/null)" || continue
    jq -er '(((.Parameters // []) | map({(.ParameterKey): .ParameterValue}) | add) // {}) as $p
      | select($p | has("LiveCode")) | "LiveCode=" + ($p.LiveCode // "") + "\nLiveSeen=" + ($p.LiveSeen // "unknown")' \
      <<<"$stack" >"$work/prev_param.$n" 2>/dev/null || rm -f "$work/prev_param.$n"
  done
}
# carry_rolling: this build verifies what the earlier one left rolling, so what that one changed and the images it replaced are
# this build's to roll back when the smoke is red. After the images (prev_image.*), before the stacks.
carry_rolling() {
  local n name old
  [[ "$(jq -r '.status // ""' <<<"$prev_build" 2>/dev/null)" = rolling ]] || return 0
  mkdir -p "$work/res"
  for n in $(jq -r '.rolling.changed // [] | .[]' <<<"$prev_build" 2>/dev/null); do : >"$work/res/$n.settled"; done
  while IFS=$'\t' read -r name old; do [[ -n "$name" ]] && printf '%s' "$old" >"$work/prev_image.$name"; done \
    < <(jq -r '.rolling.prev // {} | to_entries[] | "\(.key)\t\(.value)"' <<<"$prev_build" 2>/dev/null)
  for n in service runner; do  # LIVECODE-NOT-REFUSED: and the parameters those stacks had before it
    jq -er --arg n "$n" '.rolling.params[$n] // empty | "LiveCode=" + (.LiveCode // "") + "\nLiveSeen=" + (.LiveSeen // "unknown")' \
      <<<"$prev_build" >"$work/prev_param.$n" 2>/dev/null || rm -f "$work/prev_param.$n"
  done
}

deploy_stacks() {
  local order="$repo/infra/aws/order.json" parallel="${DEPLOY_PARALLEL:-3}" budget="${DEPLOY_BUDGET_S:-1080}"
  local begin="$started" template name n d s running=0 changed dep_ok status tag rest left_for hash stored lsig="${lambdasig:-}"
  local -A want soft rolled rolled_img
  local -a overrides
  local det roll rollhead="" settle img up f at expect=0 last_end=0 stacks_json='{}' prev_json='{}' params_json='{}' rollout_json='{}' parts_json='{}'
  [[ -n "${CODEBUILD_START_TIME:-}" ]] && begin=$((CODEBUILD_START_TIME / 1000))
  local -a names=()
  local -A tpl state deps last_secs
  mkdir -p "$work/res"
  : >"$work/done" ; : >"$work/left"
  for template in "$repo"/infra/aws/stacks/*.json; do
    name="$(basename "$template" .json | sed 's/^[0-9]*-//')"
    tpl[$name]="$template"
    if [[ -f "$order" ]] && jq -e --arg n "$name" 'has($n)' "$order" >/dev/null 2>&1; then
      deps[$name]="$(jq -r --arg n "$name" '.[$n][]' "$order" | tr '\n' ' ')"
    else
      deps[$name]="${names[*]:-}"  # not in the order file: after every stack before it, as it used to be
      echo "warning: $name is not in infra/aws/order.json, so it waits for the stacks before it"
    fi
    state[$name]=pending
    names+=("$name")
  done
  at_region=()  # MEDIA-REPLICA: the regions of this tree's stacks, read once (one jq, DEPLOY-FEWER-FORKS)
  while read -r n d; do [[ -n "$d" && -n "${tpl[$n]:-}" ]] && at_region[$n]="$d"; done \
    < <(jq -r 'to_entries[] | select(.value | test("^[a-z]{2}(-gov)?-[a-z]+-[0-9]$")) | "\(.key) \(.value)"' \
          "$repo/infra/aws/regions.json" 2>/dev/null)
  # DEP7: the targeted stacks, and every stack that needs one of them (order.json), are the ones to deploy
  if [[ "$(slurp "$work/targets" || echo all)" = all ]]; then for n in "${names[@]}"; do want[$n]=1; done
  else for n in $(<"$work/targets"); do want[$n]=1; done
    # DEP-EVENTS: a stack whose recorded hash is not the hash at this head (its last apply failed, was rolled back or never
    # happened) is always redeployed, whatever the diff says. Not inside a bisection (it deploys an older commit on purpose).
    if [[ -z "${bgood:-}" && "$(jq -r '(.hashes // {}) | length' <<<"$prev_build" 2>/dev/null || echo 0)" -gt 0 ]]; then
      for n in "${names[@]}"; do
        stored="$(jq -r --arg n "$n" '(.hashes // {})[$n] // empty' <<<"$prev_build" 2>/dev/null)"
        if [[ "$stored" != "$(stack_hash "$n")" ]]; then want[$n]=1; echo "dirty: tower-app-$n is not at the hash of this head (recorded: ${stored:-none}), redeployed whatever the diff"; fi
      done
    fi
    for _ in 1 2 3 4 5 6; do for n in "${names[@]}"; do for d in ${deps[$n]}; do [[ -n "${want[$d]:-}" ]] && want[$n]=1; done; done; done
  fi
  # SLOW-PATH-NO-ROLLOUT-WAIT: the stacks the earlier build left rolling (rolled: name -> "t0 hash", at $rollhead) are verified
  # by this build, whatever the diff says
  # VERIFY-AT-UP: and the stacks the earlier build settled at their new task's up (a green build: .rolling.settling), whose end
  # it did not wait for: complete, they are done; rolled back, their head failed (the same head) or is deployed again
  if [[ "$(jq -r '.status // ""' <<<"$prev_build" 2>/dev/null)" = rolling || "$(jq -r '.rolling.settling // false' <<<"$prev_build" 2>/dev/null)" = true ]]; then
    rollhead="$(jq -r '.rolling.head // ""' <<<"$prev_build" 2>/dev/null)"
    while read -r n at hash img; do [[ -n "${tpl[$n]:-}" ]] && { want[$n]=1; rolled[$n]="$at $hash"; rolled_img[$n]="$img"; }; done \
      < <(jq -r '(.rolling.stacks // {}) | to_entries[] | "\(.key) \(.value.t0) \(.value.hash) \(.value.image // "")"' <<<"$prev_build" 2>/dev/null)
  fi
  # DEP7-PORT-FAST-OWNED: a port stack whose only change is code the fast path already put live is not redeployed; its hash is the
  # head's (what runs), so it is not dirty, and last-build.fast_owned keeps the swaps that stand in for its older keys
  local fast_port=""
  if [[ -n "${want[port]:-}" && -n "${tpl[port]:-}" && "$(jq -r '(.hashes // {}).port // empty' <<<"$prev_build" 2>/dev/null)" != "$(stack_hash port)" ]] \
      && port_fast_owned; then
    fast_port=1; stack_hash port >"$work/res/port.hash"
  fi
  # DEP7-CRITICAL-PATH: an edge of order.json is an Fn::ImportValue, and CloudFormation refuses to change an export another stack
  # imports, so between two stacks that exist the order of their updates cannot matter for the exports. A stack waits for a
  # dependency being deployed only when that dependency does not exist yet (or is not *_COMPLETE), when its Outputs changed in
  # last-sha..head (it may add the export the stack needs), when infra/db changed (the service applies the migrations at boot and
  # the runner does not: a new runner must not start before the new schema), when last-sha is unknown, or in a bisection. Else
  # the edge is waived (soft): service and runner roll their new image out side by side instead of one after the other.
  # SLOW-PATH-NO-ROLLOUT-WAIT: the Outputs, not the whole template: a new task definition or IAM statement in 30-service.json (a
  # real infra change) exports nothing new, so the runner no longer rolls out after the service for it. And a changed infra/db
  # holds the edge only while the live service has not applied the head's migrations (migrate_wait, $work/migrated).
  if [[ -z "${bgood:-}" && "${last:-none}" != none ]] && git -C "$repo" cat-file -e "$last^{commit}" 2>/dev/null \
      && { git -C "$repo" diff --quiet "$last" "$head" -- infra/db 2>/dev/null || [[ -f "$work/migrated" ]]; }; then
    for n in "${names[@]}"; do
      [[ -n "${want[$n]:-}" ]] || continue
      for d in ${deps[$n]}; do
        [[ -n "${want[$d]:-}" && -z "${soft[$d]:-}" ]] || continue
        soft[$d]=0
        same_outputs "$d" || continue
        read -r status _ <<<"$(aws cloudformation describe-stacks --stack-name "tower-app-$d" --query 'Stacks[0].[StackStatus]' --output text 2>/dev/null)"
        [[ "$status" =~ ^(CREATE|UPDATE|UPDATE_ROLLBACK)_COMPLETE$ ]] || continue
        soft[$d]=1
        echo "order: tower-app-$d exists ($status), its exports are unchanged since ${last:0:10} and the schema is the head's: what needs it does not wait for it"
      done
    done
  fi
  while read -r n d; do last_secs[$n]="$d"; done < <(jq -r '(.stacks // {}) | to_entries[] | "\(.key | sub("^tower-app-"; "")) \(.value)"' <<<"$prev_build" 2>/dev/null)
  echo "stacks: ${names[*]}; parallel $parallel; budget ${budget}s from $(date -u -d "@$begin" +%T)"
  while :; do
    changed=0
    for n in "${names[@]}"; do
      [[ "${state[$n]}" = waiting && -f "$work/res/$n.waited" ]] && {  # SLOW-PATH-NO-ROLLOUT-WAIT: its operation ended: look again
        rm -f "$work/res/$n.waited"; state[$n]=pending; running=$((running - 1)); changed=1; step_end "wait:$n" 0
      }
      [[ "${state[$n]}" = running ]] && [[ -f "$work/res/$n" ]] && {
        read -r status d <"$work/res/$n"
        running=$((running - 1)); changed=1
        step_end "stack:$n" "$status"
        if [[ "$status" = 0 ]]; then state[$n]=ok; echo "$(TZ=UTC printf '%(%T)T' -1) end   tower-app-$n ok in ${d}s$([[ -f "$work/res/$n.rolling" ]] && echo ': its update is started and the rollout is not waited')"
        else state[$n]=failed; failed="$failed tower-app-$n"; echo "$(TZ=UTC printf '%(%T)T' -1) end   tower-app-$n FAILED (exit $status) in ${d}s"; fi
      }
    done
    for n in "${names[@]}"; do
      [[ "${state[$n]}" = pending ]] || continue
      dep_ok=1
      for d in ${deps[$n]}; do
        case "${state[$d]:-ok}" in
          ok | skipped) ;;
          failed | left) dep_ok=0; state[$n]=left; changed=1
            echo "$(TZ=UTC printf '%(%T)T' -1) not started tower-app-$n: it needs tower-app-$d, which did not finish"; break ;;
          *) [[ "${soft[$d]:-0}" = 1 ]] || dep_ok=0 ;;  # DEP7-CRITICAL-PATH: a soft edge does not wait
        esac
      done
      [[ "${state[$n]}" = pending && $dep_ok = 1 && $running -lt $parallel ]] || continue
      if [[ -z "${want[$n]:-}" ]]; then
        state[$n]=skipped; changed=1
        echo "$(TZ=UTC printf '%(%T)T' -1) skip  tower-app-$n: not a target of this batch"
        continue
      fi
      if [[ $n = port && -n "$fast_port" ]]; then
        state[$n]=skipped; changed=1
        echo "$(TZ=UTC printf '%(%T)T' -1) skip  tower-app-port: code live by the fast path (DEP7-PORT-FAST-OWNED)"
        continue
      fi
      # STACK-COMMIT-OFF-TAGS: the stack's status alone. Its commit tag is gone: a stack tag is copied to every resource that
      # takes tags, and one that changed at every apply made every apply update them all (the port stack, 11/11: 122 of its
      # 183 s on its two queues, 61 s each, one after the other; then its roles and the queue's mapping)
      read -r status _ <<<"$(aws cloudformation describe-stacks ${at_region[$n]:+--region "${at_region[$n]}"} --stack-name "tower-app-$n" \
        --query 'Stacks[0].StackStatus' --output text 2>/dev/null)"
      # SLOW-PATH-NO-ROLLOUT-WAIT: a stack in an operation (a rollout an earlier build started, and this build came before its end)
      # is waited, off the scheduler: a job reads its status at each event that may end it (stack_event). A status that
      # cannot be read (a throttled call) is not an end: the job keeps waiting, under the build's own deadline; and a stack the
      # earlier build left rolling whose status cannot be read is waited the same way, never applied on a guess.
      # VERIFY-AT-UP: a rollout still in its operation whose new task said it is up on the image the rollout deployed is SETTLED,
      # not waited: its hash is the head's, the smoke runs and last-sha moves now; the stack's end (the old task's exit, Fargate's
      # deprovision and what CloudFormation waits after ECS: 53 to 93 s live) is the next build's to verify (.rolling.settling)
      settle=""
      if [[ -n "${rolled[$n]:-}" && -n "${rolled_img[$n]:-}" && -z "${bgood:-}" && "${DEPLOY_ROLLOUT_WAIT:-0}" != 1 ]] \
          && [[ "${rolled[$n]##* }" = "$(stack_hash "$n")" ]]; then
        settle=1
      fi
      if [[ -n "$settle" && "$status" == *_IN_PROGRESS && -s "$work/res/$n.up" ]]; then
        roll="${rolled[$n]}"; read -r at <"$work/res/$n.up"
        echo "${roll##* }" >"$work/res/$n.hash"; echo "${roll%% *} ${roll##* } $(( ${at%.*} - ${roll%% *} ))" >"$work/res/$n.settling"
        state[$n]=skipped; changed=1
        echo "$(TZ=UTC printf '%(%T)T' -1) done  tower-app-$n: up at ${rollhead:0:10}, its new task said so $(( ${at%.*} - ${roll%% *} ))s after the update started; the stack is $status, its end is the next build's to verify"
        continue
      fi
      if [[ "$status" == *_IN_PROGRESS || ( -z "$status" && -n "${rolled[$n]:-}" ) ]]; then
        state[$n]=waiting; running=$((running + 1)); changed=1
        step_begin "wait:$n"
        echo "$(TZ=UTC printf '%(%T)T' -1) wait  tower-app-$n: ${status:-status unreadable}, an operation an earlier build started: this build waits for its end${settle:+ or the up of its new task}"
        ( seen=""  # STACK-END-BY-EVENT (D-331): each look is the answer to an event (stack_event), never a read on an interval
          while read -r status _ <<<"$(aws cloudformation describe-stacks ${at_region[$n]:+--region "${at_region[$n]}"} --stack-name "tower-app-$n" --query 'Stacks[0].StackStatus' --output text 2>/dev/null)"
                [[ -z "$status" || "$status" == *_IN_PROGRESS ]]; do
            if [[ -n "$settle" && "$status" == *_IN_PROGRESS ]] && up_seen "$n" "${rolled[$n]%% *}" "${rolled_img[$n]}" >"$work/res/$n.up.tmp" \
                && [[ -s "$work/res/$n.up.tmp" ]]; then
              mv "$work/res/$n.up.tmp" "$work/res/$n.up"; break
            fi
            seen="$(stack_event "$n" "$status" "$seen")"
          done
          : >"$work/res/$n.waited" ) &
        continue
      fi
      # SLOW-PATH-NO-ROLLOUT-WAIT: the rollout the earlier build started. Complete at that head: done, with its seconds (and its hash
      # is the one that build computed). Not complete and this build deploys that same head: the update failed and CloudFormation
      # rolled the stack back (the ECS circuit breaker, a failed resource): a failed stack, never deployed again by this build. A
      # head that moved since is deployed below, like any head after a failed batch (DEP7-NEW-HEAD-FIRST).
      roll="${rolled[$n]:-}"; stored=""
      if [[ -n "$roll" && "$status" =~ ^(CREATE|UPDATE)_COMPLETE$ ]]; then
        rolled_out "$n" "${roll%% *}"; stored="${roll##* }"
        # ROLLOUT-PARTS: and where that rollout's seconds went on CloudFormation's side (the Service resource against the
        # stack's end: what it waited after the ECS deployment), in last-build.parts like a stack that was waited
        slow_parts "$n" "${roll%% *}" >"$work/res/$n.parts" 2>/dev/null; [[ -s "$work/res/$n.parts" ]] && echo "[$n] parts: $(<"$work/res/$n.parts")" || rm -f "$work/res/$n.parts"
        echo "$(TZ=UTC printf '%(%T)T' -1) done  tower-app-$n: rolled out at ${rollhead:0:10}$([[ -f "$work/res/$n.roll" ]] && echo " in $(<"$work/res/$n.roll")s, off the build's clock")"
      elif [[ -n "$roll" && "$rollhead" = "$head" && -n "$status" ]]; then
        state[$n]=failed; failed="$failed tower-app-$n"; changed=1
        step_begin "stack:$n"
        echo "$(TZ=UTC printf '%(%T)T' -1) end   tower-app-$n FAILED: the rollout started at ${rollhead:0:10} did not complete: the stack is ${status:-unreadable} (rolled back)"
        failed_events "$n" "${roll%% *}" 2>&1 | sed -u "s/^/[$n] /"
        step_end "stack:$n" 1
        continue
      fi
      hash="$(stack_hash "$n")"
      [[ -n "$stored" ]] || stored="$(jq -r --arg n "$n" '(.hashes // {})[$n] // empty' <<<"$prev_build" 2>/dev/null)"
      if [[ -n "$stored" && "$stored" = "$hash" && "$status" =~ ^(CREATE|UPDATE)_COMPLETE$ ]]; then
        state[$n]=skipped; changed=1
        echo "$(TZ=UTC printf '%(%T)T' -1) skip  tower-app-$n: template and images unchanged since the last apply ($hash)"
        echo "$hash" >"$work/res/$n.hash"
        continue
      fi
      left_for=$((budget - (${DEPLOY_NOW:-$EPOCHSECONDS} - begin)))  # DEPLOY_NOW: a test pins the clock; a build leaves it unset
      if (( left_for < ${last_secs[$n]:-0} )); then
        state[$n]=left; changed=1
        echo "$(TZ=UTC printf '%(%T)T' -1) not started tower-app-$n: ${left_for}s of the ${budget}s budget remain, its last deploy took ${last_secs[$n]:-0}s"
        continue
      fi
      [[ $n = port ]] && echo null >"$work/fast_owned"  # DEP7-PORT-FAST-OWNED: a real apply passes every current key
      # SLOW-PATH-NO-ROLLOUT-WAIT: a stack with an ECS service that exists is started and not waited: the rollout (a new task, its
      # image pull, its health, the old one's drain) is verified by the next build. Not when a pending stack of this batch must
      # have it complete (a hard edge), in a bisection, or with DEPLOY_ROLLOUT_WAIT=1.
      det=""
      if [[ -z "${bgood:-}" && "${DEPLOY_ROLLOUT_WAIT:-0}" != 1 && "$status" =~ ^(CREATE|UPDATE|UPDATE_ROLLBACK)_COMPLETE$ ]] \
          && grep -q '"AWS::ECS::Service"' "${tpl[$n]}"; then
        det=1
        for d in "${names[@]}"; do
          [[ "${state[$d]}" = pending && -n "${want[$d]:-}" && " ${deps[$d]} " == *" $n "* && "${soft[$n]:-0}" != 1 ]] && det=""
        done
      fi
      state[$n]=running; running=$((running + 1)); changed=1
      step_begin "stack:$n"
      echo "$(TZ=UTC printf '%(%T)T' -1) start tower-app-$n from ${tpl[$n]} (${left_for}s of budget remain)${det:+: its rollout will not be waited}"
      (
        t0="$EPOCHSECONDS"
        overrides=(); [[ $n = port && -n "${lambda_params[*]:-}" ]] && overrides=(--parameter-overrides "${lambda_params[@]}")  # PortCode, DepsKey
        # IMAGE-PREWARM-C: LiveCode; SLOW-PATH-NO-ROLLOUT-WAIT: LiveSeen, the datum this deploy saw
        [[ $n = service || $n = runner ]] && overrides=(--parameter-overrides "LiveCode=$(slurp "$work/livecode")" "LiveSeen=$(slurp "$work/liveseen" || echo unknown)")
        # DB-MEDIUM, SERVICE-MEMORY: a stack's values from infra/aws/parameters.json, beside its own (`aws cloudformation
        # deploy` keeps a parameter's previous value when it is not given, so a template Default never reaches the stack): the
        # database's class, the service's memory
        mapfile -t file_params < <(jq -r --arg n "$n" '.[$n] // {} | to_entries[] | "\(.key)=\(.value)"' "$repo/infra/aws/parameters.json" 2>/dev/null)
        if (( ${#file_params[@]} )); then
          if (( ${#overrides[@]} )); then overrides+=("${file_params[@]}"); else overrides=(--parameter-overrides "${file_params[@]}"); fi
        fi
        aws cloudformation deploy ${at_region[$n]:+--region "${at_region[$n]}"} --stack-name "tower-app-$n" --template-file "${tpl[$n]}" --role-arn "$CFN_EXEC_ROLE_ARN" \
          --capabilities CAPABILITY_NAMED_IAM --no-fail-on-empty-changeset ${det:+--no-execute-changeset} ${overrides[@]+"${overrides[@]}"} --tags project=tower 2>&1 \
          | tee "$work/res/$n.log" | sed -u "s/^/[$n] /"
        code="${PIPESTATUS[0]}"
        # SLOW-PATH-NO-ROLLOUT-WAIT: the change set the CLI created and did not execute (it prints its ARN) is executed here, and
        # nothing waits for the stack: res/<n>.rolling = "<start> <hash>" is what the next build verifies
        if [[ $code = 0 && -n "$det" ]] && ! grep -q 'No changes to deploy' "$work/res/$n.log"; then
          arn="$(grep -o 'arn:aws[^ ]*:cloudformation:[^ ]*:changeSet/[^ ]*' "$work/res/$n.log" | tail -n 1)"
          if [[ -z "$arn" ]]; then echo "[$n] no change set to execute in the output of the deploy"; code=1
          else aws cloudformation execute-change-set ${at_region[$n]:+--region "${at_region[$n]}"} --change-set-name "$arn" 2>&1 | tee -a "$work/res/$n.log" | sed -u "s/^/[$n] /"; code="${PIPESTATUS[0]}"; fi
          [[ $code = 0 ]] && echo "$EPOCHSECONDS $hash" >"$work/res/$n.rolling"
        fi
        # a failed stack: its FAILED events (ResourceStatusReason) go to the build log, so GET /v1/deploy/status shows why
        [[ $code = 0 ]] || failed_events "$n" "$t0" 2>&1 | sed -u "s/^/[$n] /"
        # a deploy without changes takes seconds: it must not replace the recorded duration of a real one
        if [[ $code = 0 ]] && ! grep -q 'No changes to deploy' "$work/res/$n.log"; then echo "$(( $EPOCHSECONDS - t0 ))" >"$work/res/$n.secs"; fi
        # SLOW-PATH-STACK-PARTS: a real change that was waited says where its seconds went (last-build.parts, and the build's log)
        if [[ -f "$work/res/$n.secs" && ! -f "$work/res/$n.rolling" ]]; then
          slow_parts "$n" "$t0" >"$work/res/$n.parts" 2>/dev/null; [[ -s "$work/res/$n.parts" ]] && echo "[$n] parts: $(<"$work/res/$n.parts")" || rm -f "$work/res/$n.parts"
        fi
        [[ $code = 0 && ! -f "$work/res/$n.rolling" ]] && echo "$hash" >"$work/res/$n.hash"
        [[ $n = port && $code = 0 ]] && sha256sum <"${tpl[port]}" | cut -c1-20 >"$work/port_tpl"  # STACK-COMMIT-OFF-TAGS
        echo "$code $(( $EPOCHSECONDS - t0 ))" >"$work/res/$n.tmp" && mv "$work/res/$n.tmp" "$work/res/$n"
      ) &
    done
    if (( running == 0 )); then
      (( changed )) && continue
      break
    fi
    (( changed )) || wait -n || true
  done
  secs_json='{}'
  for n in "${names[@]}"; do
    case "${state[$n]}" in
      ok | skipped) echo "tower-app-$n" >>"$work/done" ;;
      left) echo "tower-app-$n" >>"$work/left" ;;
    esac
    [[ -f "$work/res/$n.secs" ]] && secs_json="$(jq -c --arg k "tower-app-$n" --argjson v "$(<"$work/res/$n.secs")" '. + {($k): $v}' <<<"$secs_json")"
  done
  echo "$secs_json" >"$work/secs"
  for f in "$work"/res/*.parts; do  # SLOW-PATH-STACK-PARTS
    [[ -s "$f" ]] && parts_json="$(jq -c --arg k "tower-app-$(basename "$f" .parts)" --slurpfile v "$f" '. + {($k): $v[0]}' <<<"$parts_json")"
  done
  echo "$parts_json" >"$work/parts"
  # SLOW-PATH-NO-ROLLOUT-WAIT: the rollouts this build verified: each stack's seconds (rollout) and, from the end of the build that
  # started them to the last one stable, the wait that is no longer on any build's clock (rollout_wait_s)
  for f in "$work"/res/*.roll; do
    [[ -f "$f" ]] || continue
    n="$(basename "$f" .roll)"; rollout_json="$(jq -c --arg k "tower-app-$n" --argjson v "$(<"$f")" '. + {($k): $v}' <<<"$rollout_json")"
    at="$(<"$work/res/$n.rollend")"; (( at > last_end )) && last_end=$at
  done
  echo "$rollout_json" >"$work/rollout"
  d="$(jq -r '.ended // 0' <<<"$prev_build" 2>/dev/null)"
  if [[ "$d" =~ ^[0-9]+$ ]] && (( last_end > 0 && d > 0 )); then echo $(( last_end > d ? last_end - d : 0 )) >"$work/rollout_wait"; fi
  # ... and the rollouts it started: last-build.rolling, for the build that verifies them. until = the last of their expected
  # ends (each stack's start plus its last rollout; DEPLOY_ROLLOUT_EXPECT_S, default 600, when none was measured) plus
  # DEPLOY_ROLLOUT_MARGIN_S (60): when the service rings that build even if no task of the stacks said it is up and no stack
  # event came. From each stack's start, not from this build's end: what the build did after it (the port stack) is no part of
  # a rollout. prev = the images before this build (what a red smoke puts back).
  # VERIFY-AT-UP: image = what the stack's tasks run (the first image its template reads): a task up on it is the rollout's
  for f in "$work"/res/*.rolling; do
    [[ -f "$f" ]] || continue
    n="$(basename "$f" .rolling)"; read -r at hash <"$f"
    img="$(grep -o '/tower/deploy/image/[A-Za-z0-9_-]*' "${tpl[$n]}" | head -n 1)"; img="$([[ -n "$img" ]] && cat "$work/img/${img##*/}" 2>/dev/null)"
    stacks_json="$(jq -c --arg n "$n" --argjson t "$at" --arg h "$hash" --arg i "$img" '. + {($n): ({t0: $t, hash: $h} + (if $i == "" then {} else {image: $i} end))}' <<<"$stacks_json")"
    d="$(jq -r --arg k "tower-app-$n" '(.rollout // {})[$k] // empty' <<<"$prev_build" 2>/dev/null)"; [[ "$d" =~ ^[0-9]+$ ]] || d="${DEPLOY_ROLLOUT_EXPECT_S:-600}"
    (( at + d > expect )) && expect=$((at + d))
  done
  # VERIFY-AT-UP: the stacks settled at their new task's up: their end is the next build's to verify (with what the build that
  # started them recorded, and `up`, the seconds from the update's start to that up). Alone (no rollout started here) they
  # make last-build.rolling {head: the rollout's, settling: true, stacks}: the build is green and last-sha moves
  local settling_json='{}'
  for f in "$work"/res/*.settling; do
    [[ -f "$f" ]] || continue
    n="$(basename "$f" .settling)"; read -r at hash up <"$f"
    settling_json="$(jq -c --arg n "$n" --argjson t "$at" --arg h "$hash" --arg i "${rolled_img[$n]:-}" --argjson u "${up:-null}" \
      '. + {($n): {t0: $t, hash: $h, image: $i, up: $u}}' <<<"$settling_json")"
  done
  if [[ "$stacks_json" = '{}' && "$settling_json" != '{}' ]]; then
    jq -nc --arg h "$rollhead" --argjson s "$settling_json" '{head: $h, settling: true, until: 0, stacks: $s}' >"$work/rolling"
  fi
  stacks_json="$(jq -c --argjson s "$settling_json" '$s + .' <<<"$stacks_json")"
  if [[ "$stacks_json" != "$settling_json" ]]; then
    for f in "$work"/prev_image.*; do [[ -f "$f" ]] && prev_json="$(jq -c --arg k "${f##*/prev_image.}" --arg v "$(<"$f")" '. + {($k): $v}' <<<"$prev_json")"; done
    params_json='{}'  # LIVECODE-NOT-REFUSED: the parameters the stacks had before this build, for the build that verifies it
    for f in "$work"/prev_param.*; do
      [[ -f "$f" ]] && params_json="$(jq -c --arg k "${f##*/prev_param.}" --arg c "$(sed -n 's/^LiveCode=//p' "$f")" --arg s "$(sed -n 's/^LiveSeen=//p' "$f")" \
        '. + {($k): {LiveCode: $c, LiveSeen: $s}}' <<<"$params_json")"
    done
    jq -nc --arg h "$head" --argjson u "$(( expect + ${DEPLOY_ROLLOUT_MARGIN_S:-60} ))" --argjson s "$stacks_json" \
      --argjson c "$(changed_stacks | jq -R . | jq -sc .)" --argjson p "$prev_json" --argjson q "$params_json" \
      '{head: $h, until: $u, stacks: $s, changed: $c, prev: $p} + (if $q == {} then {} else {params: $q} end)' >"$work/rolling"
  fi
  # DEP-EVENTS: last-sha never moves while a stack is dirty (its recorded or just applied hash is not the one at this head)
  : >"$work/dirty"
  if [[ -z "${bgood:-}" && "$(jq -r '(.hashes // {}) | length' <<<"$prev_build" 2>/dev/null || echo 0)" -gt 0 ]]; then
    for n in "${names[@]}"; do
      [[ -f "$work/res/$n.rolling" ]] && continue  # SLOW-PATH-NO-ROLLOUT-WAIT: rolling out, not dirty: the next build verifies it
      if [[ -f "$work/res/$n.hash" ]]; then stored="$(<"$work/res/$n.hash")"; else stored="$(jq -r --arg n "$n" '(.hashes // {})[$n] // empty' <<<"$prev_build" 2>/dev/null)"; fi
      [[ "$stored" = "$(stack_hash "$n")" ]] || echo "tower-app-$n" >>"$work/dirty"
    done
  fi
  echo "stacks done: $(tr '\n' ' ' <"$work/done")| left: $(tr '\n' ' ' <"$work/left")"
}

# GATE-SHUTDOWN (D-314): the deployer no longer deploys the Cloudflare Worker forge-webhook (services/control-plane): it served
# the AWS gate's Origin webhooks, and it stays where it is, outside AWS; nothing here reads the Cloudflare token.

# smoke: the post-deploy check (scripts/deploy-smoke: GET /v1/health, GET /v1/deploy/status, a registry read). Only when a
# stack really changed in this build. DEPLOY_SMOKE_CMD replaces the command (a test); "none" skips it.
smoke() {
  local cmd="${DEPLOY_SMOKE_CMD:-$ctl/scripts/deploy-smoke}"
  [[ -n "$(changed_stacks)" || -f "$work/reloaded" ]] || { echo "smoke: no stack changed in this build, not run"; return 0; }  # FAST-PATH-RELOAD
  [[ "$cmd" = none ]] && { echo "smoke: skipped (DEPLOY_SMOKE_CMD=none)"; return 0; }
  [[ -x "${cmd%% *}" || "$cmd" != "$ctl/scripts/deploy-smoke" ]] || { echo "smoke: $cmd is missing, not run"; return 0; }
  echo "smoke: $cmd"
  bash -c "$cmd" 2>&1 | sed -u 's/^/[smoke] /'
  [[ "${PIPESTATUS[0]}" = 0 ]]
}

# rollback <last>: the stacks this build really changed go back to the template of <last> and the images to the ones
# recorded before this build (CloudFormation already rolled back by itself a stack that FAILED; this is for a green
# deploy that the smoke refused; changed_stacks). Lists the stacks it restored in $work/rolled; a stack with no template at <last>
# (a new one) is left and named in the output.
rollback() {
  local last="$1" f n name file old failed_back="" seen
  local -a back
  [[ "$last" != none ]] && git -C "$repo" cat-file -e "$last^{commit}" 2>/dev/null || { echo "rollback: no previous sha, nothing to restore"; return 1; }
  for f in "$work"/prev_image.*; do
    [[ -f "$f" ]] || continue
    name="${f##*/prev_image.}"; old="$(<"$f")"
    [[ -n "$old" ]] && aws ssm put-parameter --name "/tower/deploy/image/$name" --type String --overwrite --value "$old" >/dev/null
  done
  for n in $(changed_stacks); do  # SLOW-PATH-NO-ROLLOUT-WAIT: also what the build that left stacks rolling changed
    file="$(cd "$repo" && ls infra/aws/stacks/*-"$n".json 2>/dev/null | head -1)"
    if [[ -z "$file" ]] || ! git -C "$repo" cat-file -e "$last:$file" 2>/dev/null; then echo "rollback: tower-app-$n has no template at $last, left as it is"; continue; fi
    git -C "$repo" show "$last:$file" >"$work/rollback-$n.json"
    # VERIFY-AT-UP: a stack this build settled at its new task's up may still be in its operation: its end first
    # STACK-END-BY-EVENT (D-331): looked at again at each event that may end it (stack_event), never on an interval
    seen=""
    while read -r status _ <<<"$(aws cloudformation describe-stacks ${at_region[$n]:+--region "${at_region[$n]}"} --stack-name "tower-app-$n" --query 'Stacks[0].StackStatus' --output text 2>/dev/null)"
          [[ "$status" == *_IN_PROGRESS ]]; do seen="$(stack_event "$n" "$status" "$seen")"; done
    back=()  # LIVECODE-NOT-REFUSED: the parameters the stack had before the deploy that is undone (prev_params)
    [[ -f "$work/prev_param.$n" ]] && mapfile -t back <"$work/prev_param.$n" && back=(--parameter-overrides "${back[@]}")
    echo "rollback: tower-app-$n to $last${back[1]:+ (${back[1]:0:21})}"
    if aws cloudformation deploy ${at_region[$n]:+--region "${at_region[$n]}"} --stack-name "tower-app-$n" --template-file "$work/rollback-$n.json" --role-arn "$CFN_EXEC_ROLE_ARN" \
        --capabilities CAPABILITY_NAMED_IAM --no-fail-on-empty-changeset ${back[@]+"${back[@]}"} --tags project=tower 2>&1 | sed -u "s/^/[rollback $n] /"; [[ "${PIPESTATUS[0]}" = 0 ]]; then
      echo "tower-app-$n" >>"$work/rolled"
    else
      failed_back="$failed_back rollback:$n"
    fi
  done
  [[ -z "$failed_back" ]] || { failed="$failed$failed_back"; return 1; }
}

# bisect_state <last> <head> <good> <bad>: after a failed build, the bisection state for the record (DEP7). <good>/<bad> are
# the bounds of a bisection in progress (empty: this was the whole batch (last, head]). Halves the slow commits of the range:
# the next build deploys the first half, then the other; one slow commit left that fails is the culprit.
bisect_state() {
  local last="$1" head="$2" good="$3" bad="$4" base lo hi n
  local -a commits
  if [[ -n "$good" ]]; then lo="$good"; hi="$bad"; else lo="$last"; hi="$head"; fi
  if [[ "$lo" = none ]] || ! git -C "$repo" cat-file -e "$lo^{commit}" 2>/dev/null; then echo null >"$work/bisect"; return; fi
  mapfile -t commits < <(slow_commits "$lo" "$hi")
  n=${#commits[@]}
  if [[ -n "$good" && "$head" != "$bad" ]]; then  # the middle failed: the culprit is in (good, head]
    hi="$head"; mapfile -t commits < <(slow_commits "$lo" "$hi"); n=${#commits[@]}
  fi
  # head_tried_sha: the newest BASE head a build deployed and that failed. A whole-batch or head-first build is one (its head is the
  # base head); a midpoint build keeps the one it inherited. The next build deploys the current head first whenever it differs.
  local tried="${btried:-}"; { [[ -z "$good" ]] || (( ${hfirst:-0} )); } && tried="$head"
  if (( n <= 1 )); then
    jq -nc --arg c "${commits[0]:-$hi}" --arg g "$lo" --arg b "$hi" --arg t "$tried" --arg r "${bnote:+$bnote; }the last slow commit of the range failed" \
      '{culprit: $c, good: $g, bad: $b, builds: 0, head_tried_sha: $t, reason: $r}' >"$work/bisect"
    echo "bisect: culprit ${commits[0]:-$hi}"
  else
    jq -nc --arg g "$lo" --arg b "$hi" --argjson n "$n" --argjson k "${bbuilds:-0}" --arg t "$tried" --arg r "${bnote:+$bnote; }$n slow commits in range failed together" \
      '{good: $g, bad: $b, n: $n, builds: $k, head_tried_sha: $t, reason: $r}' >"$work/bisect"
    echo "bisect: $n slow commits in (${lo:0:10}, ${hi:0:10}], the next build deploys the first half"
  fi
}

# bisect_usable <state json> <last> <base head>: 0 when the earlier bisection may steer this build; else $bnote says why not.
bisect_usable() {
  local bis="$1" last="$2" base="$3" epoch good bad builds
  bnote=""
  [[ -n "$bis" && "$bis" != null ]] || return 1
  epoch="$(jq -r '.bisect_epoch // 0' <<<"$prev_build" 2>/dev/null)"
  if [[ "$epoch" != "$BISECT_EPOCH" ]]; then bnote="bisect ignored: epoch $epoch is not $BISECT_EPOCH (a state of an older deployer)"; return 1; fi
  if jq -e '.culprit' <<<"$bis" >/dev/null 2>&1; then bnote="culprit $(jq -r .culprit <<<"$bis" | cut -c1-10) does not block: the head is deployed again"; return 1; fi
  jq -e '.good and .bad' <<<"$bis" >/dev/null 2>&1 || { bnote="bisect ignored: malformed"; return 1; }
  good="$(jq -r .good <<<"$bis")"; bad="$(jq -r .bad <<<"$bis")"; builds="$(jq -r '.builds // 0' <<<"$bis")"
  if [[ "$builds" =~ ^[0-9]+$ ]] && (( builds >= bisect_max_builds )); then bnote="bisect dropped: $builds builds (max $bisect_max_builds)"; return 1; fi
  if [[ "$good" != "$last" ]]; then bnote="bisect dropped: good ${good:0:10} is not last-sha"; return 1; fi
  if ! git -C "$repo" cat-file -e "$bad^{commit}" 2>/dev/null || ! git -C "$repo" merge-base --is-ancestor "$bad" "$base" 2>/dev/null; then
    bnote="bisect dropped: bad ${bad:0:10} is not in the history of the base branch"; return 1
  fi
  bbuilds=$((builds + 1))
  return 0
}

deploy() {
  head="$(git -C "$repo" rev-parse HEAD)" || return 1
  echo "$head" >"$work/head"  # the pipeline runs this function in a subshell: its results travel in files
  last="$(aws ssm get-parameter --name /tower/deploy/last-sha --query Parameter.Value --output text 2>/dev/null || echo none)"
  echo "base head $head"
  echo "last deployed $last"
  failed=""
  # (an unreadable last-build is no evidence of a failure; a failed or incomplete one, or one with dirty stacks, is)
  if [ "$head" = "$last" ] && ! [[ "$(jq -r '.status // ""' <<<"$prev_build" 2>/dev/null)" =~ ^(failed|incomplete)$ ]] \
      && [[ "$(jq -r '(.dirty // []) | length' <<<"$prev_build" 2>/dev/null || echo 0)" =~ ^(0|)$ ]]; then
    echo "nothing new"
    echo nothing_new >"$work/status"
    echo null >"$work/bisect"  # everything is deployed: no bisection can be pending
    return 0
  fi
  # DEP7: a bisection in progress (last-build.bisect, good == last-sha) deploys a commit inside the failed batch, not HEAD
  bgood=""; bbad=""; bnote=""; bbuilds=0; hfirst=0; btried=
  # the head's scripts, before any checkout of a midpoint replaces the tree
  if mkdir -p "$work/ctl" && git -C "$repo" archive HEAD scripts 2>/dev/null | tar -x -C "$work/ctl" 2>/dev/null && [[ -d "$work/ctl/scripts" ]]; then ctl="$work/ctl"; fi
  local bis n_slow mid base_head="$head"
  bis="$(jq -c '.bisect // empty' <<<"$prev_build" 2>/dev/null)"
  if bisect_usable "$bis" "$last" "$base_head"; then
    bgood="$last"; bbad="$(jq -r .bad <<<"$bis")"; btried="$(jq -r '.head_tried_sha // ""' <<<"$bis")"
    local -a slow
    if [[ "$base_head" != "$btried" && "$base_head" != "$bbad" ]]; then
      # DEP7-NEW-HEAD-FIRST: a head that is not the last one tried (a commit landed since, whether the state is fresh or mid-bisection) is
      # deployed BEFORE any midpoint: it may contain the fix. Green clears the state; red bisects (last-sha, this head]. No clock, events only.
      hfirst=1; bnote="head first: ${base_head:0:10} is not the last tried head ${btried:0:10} (bad ${bbad:0:10}), deployed before any midpoint"
      bgood=""; bbad=""
    fi
    if (( ! hfirst )); then
      mapfile -t slow < <(slow_commits "$bgood" "$bbad"); n_slow=${#slow[@]}
      # adjacent (or the only slow commit): the midpoint IS bad, so this build is the last step and never repeats a commit
      if (( n_slow >= 2 )); then mid="${slow[$((n_slow / 2 - 1))]}"; else mid="$bbad"; fi
      [[ "$mid" != "$last" ]] || mid="$bbad"
      if git -C "$repo" checkout -q --detach "$mid" 2>/dev/null; then
        head="$mid"; echo "$head" >"$work/head"
        echo "bisect: deploying $head, the first of the $n_slow slow commits of (${bgood:0:10}, ${bbad:0:10}]"
      else bgood=""; bnote="bisect dropped: $mid cannot be checked out"; fi
    fi
  fi
  [[ -z "$bnote" ]] || { echo "$bnote"; echo "$bnote" >"$work/bnote"; }
  echo "$(slow_commits "$last" "$head" | wc -l | tr -d ' ')" >"$work/batch"
  step_begin classify
  select_targets "$last"
  step_end classify 0
  lambda_bucket="tower-outputs-${IMAGE_REGISTRY%%.*}-${AWS_REGION:-${AWS_DEFAULT_REGION:-us-east-1}}"
  if [[ "$(<"$work/image")" = 1 ]]; then  # SLOW-PATH-NO-ROLLOUT-WAIT
    step_begin code-live
    if code_live; then step_end code-live 0
    else
      step_end code-live 0
      if [[ -s "$work/code_digest" ]]; then step_begin reload; reload_live; step_end reload 0; fi  # FAST-PATH-RELOAD
    fi
  elif [[ -s "$work/classify.json" ]]; then  # HEAD-CODE-LIVE: no image in this batch: the head's code may be live already
    step_begin code-live
    code_live head || :
    step_end code-live 0
  fi
  migrate_ask
  shopt -s nullglob
  for dockerfile in "$repo"/infra/*/Dockerfile; do
    [[ "$(<"$work/image")" = 1 ]] || { echo "image: not a target of this batch"; break; }
    name="$(basename "$(dirname "$dockerfile")")"
    repository="tower-$name"
    step_begin "image:$name"
    tag="$(git -C "$repo" rev-parse "HEAD:infra/$name" "HEAD:infra/db" | sha256sum | cut -c1-20)"
    image="$IMAGE_REGISTRY/$repository:$tag"
    aws ecr describe-repositories --repository-names "$repository" >/dev/null 2>&1 \
      || { aws ecr create-repository --repository-name "$repository" --image-tag-mutability IMMUTABLE \
             --image-scanning-configuration scanOnPush=true >/dev/null \
           && aws ecr put-lifecycle-policy --repository-name "$repository" --lifecycle-policy-text \
             '{"rules":[{"rulePriority":1,"selection":{"tagStatus":"any","countType":"imageCountMoreThan","countNumber":10},"action":{"type":"expire"}}]}' >/dev/null; }
    if aws ecr describe-images --repository-name "$repository" --image-ids imageTag="$tag" >/dev/null 2>&1; then
      echo "image $image is already built"
    elif aws ecr get-login-password | docker login --username AWS --password-stdin "$IMAGE_REGISTRY" >/dev/null \
        && { prior="$(aws ssm get-parameter --name "/tower/deploy/image/$name" --query Parameter.Value --output text 2>/dev/null)" || prior=""
             cache=(); [[ -n "$prior" && "$prior" != None ]] && docker pull --quiet "$prior" >/dev/null 2>&1 && cache=(--cache-from "$prior"); true; } \
        && { stage_cache "$dockerfile" "$repository"; cache+=(${stage_from[@]+"${stage_from[@]}"}); true; } \
        && docker build --quiet ${cache[@]+"${cache[@]}"} --build-arg BUILDKIT_INLINE_CACHE=1 --file "$dockerfile" --tag "$image" "$repo" \
        && docker push --quiet "$image"; then
      echo "built $image from $dockerfile"
    else
      echo "image $name failed"
      failed="$failed image:$name"
      step_end "image:$name" 1
      continue
    fi
    step_end "image:$name" 0
    prior="$(aws ssm get-parameter --name "/tower/deploy/image/$name" --query Parameter.Value --output text 2>/dev/null)" || prior=""
    [[ "$prior" = None ]] && prior=""
    printf '%s' "$prior" >"$work/prev_image.$name"  # what the rollback puts back
    aws ssm put-parameter --name "/tower/deploy/image/$name" --type String --overwrite --value "$image" >/dev/null \
      || failed="$failed record:$name"
  done
  # the images the stacks will read, in the hash of the stacks that name them: a new image redeploys the stacks that use it
  mkdir -p "$work/img"
  for dockerfile in "$repo"/infra/*/Dockerfile; do
    name="$(basename "$(dirname "$dockerfile")")"
    printf '%s' "$(aws ssm get-parameter --name "/tower/deploy/image/$name" --query Parameter.Value --output text 2>/dev/null)" >"$work/img/$name"
  done
  lambdasig=""
  # DEP8: the zip packages and the layer the 40-port stack starts from (content-addressed in the outputs bucket, so a rerun
  # uploads nothing) and the keys the stack reads; they join the stacks' hash like the images, so a changed package redeploys port
  lambda_cmd="${DEPLOY_LAMBDA_PACKAGE_CMD:-python3 $ctl/scripts/lib/lambda_package.py publish --root $repo}"
  step_begin lambda-package
  lambda_rc=0
  # FAIL FAST (DEP-WATCHDOG): the real command first checks pip and that the deployer may write to the bucket, so a missing
  # permission is one clear line in last-build in seconds, not a build that hangs or a message buried in the log
  if [[ -z "${DEPLOY_LAMBDA_PACKAGE_CMD:-}" ]]; then
    if ! python3 -m pip --version >/dev/null 2>&1; then
      echo "lambda packages: python3 -m pip is missing in this image (the layer build needs it)"; lambda_rc=1
    elif ! printf '' | timeout 60 aws s3 cp - "s3://$lambda_bucket/artifacts/lambda/.deployer-probe" --only-show-errors 2>"$work/probe.err"; then
      echo "lambda packages: the deployer cannot write s3://$lambda_bucket/artifacts/lambda/*: $(head -c 300 "$work/probe.err" | tr '\n' ' ')"
      echo "PEDIDO A TORRE (docs/operations/aws.md, DEP-WATCHDOG): DeployerRole needs s3:PutObject and s3:GetObject on arn:<partition>:s3:::$lambda_bucket/artifacts/lambda/* and (no SSM write for the keys any more)"
      lambda_rc=1
    fi
  fi
  if (( lambda_rc == 0 )); then
    TOWER_ARTIFACT_BUCKET="$lambda_bucket" timeout "${DEPLOY_STEP_TIMEOUT_S:-900}" bash -c "$lambda_cmd" 2>&1 | tee "$work/lambda.out"
    lambda_rc="${PIPESTATUS[0]}"
    if (( lambda_rc == 124 )); then echo "lambda packages: timed out after ${DEPLOY_STEP_TIMEOUT_S:-900}s"; fi
    if grep -qE 'AccessDenied|not authorized|is not authorized' "$work/lambda.out" 2>/dev/null; then
      echo "PEDIDO A TORRE (docs/operations/aws.md, DEP-WATCHDOG): DeployerRole is denied: needs s3:PutObject and s3:GetObject on arn:<partition>:s3:::$lambda_bucket/artifacts/lambda/* and (no SSM write for the keys any more)"
      lambda_rc=13
    fi
  fi
  lambda_params=()
  if (( lambda_rc == 0 )); then
    # no SSM for the keys (the deployer role may not PutParameter there): publish prints them as one JSON line, passed to the port stack
    lambda_keys="$(grep '^{' "$work/lambda.out" 2>/dev/null | tail -n 1)"
    if [[ -n "${DEPLOY_LAMBDA_PACKAGE_CMD:-}" && -z "$lambda_keys" ]]; then :; elif jq -e type <<<"$lambda_keys" >/dev/null 2>&1; then
      for pair in PortCode:tower-port-api DepsKey:deps; do  # GATE-SHUTDOWN: the port stack's only Lambda and its layer
        value="$(jq -r --arg k "${pair#*:}" '.[$k] // empty' <<<"$lambda_keys")"
        [[ -n "$value" ]] && { lambda_params+=("${pair%%:*}=$value"); lambdasig="$lambdasig$value"; }
      done
    else
      echo "lambda packages: no JSON line of keys in the output of $lambda_cmd"; lambda_rc=2
    fi
  fi
  step_end lambda-package "$lambda_rc"
  if (( lambda_rc != 0 )); then
    echo "lambda packages failed"; failed="$failed lambda-package"
    # a missing permission or a missing tool will not fix itself in this build: stop here, the record says why
    if (( lambda_rc == 1 || lambda_rc == 13 )); then echo "failed fast:$failed; /tower/deploy/last-sha stays $last"; echo "$failed" >"$work/failed"; return 1; fi
  fi
  live_code
  migrate_wait
  carry_rolling
  prev_params
  deploy_stacks
  # SLOW-PATH-NO-ROLLOUT-WAIT: stacks are rolling out: the build ends here, in seconds; the smoke, the rollback and last-sha are
  # the next build's, which verifies them (a bisection in progress keeps its state: this build decided nothing)
  if [ -z "$failed" ] && [ ! -s "$work/left" ] && [ -s "$work/rolling" ] && ! jq -e '.settling == true' "$work/rolling" >/dev/null 2>&1; then
    echo "rolling: $(jq -r '.stacks | keys | map("tower-app-" + .) | join(" ")' "$work/rolling") started and not waited; /tower/deploy/last-sha stays $last until the next build verifies them (rung at their end, at $(date -u -d "@$(jq -r .until "$work/rolling")" +%T) at the latest)"
    echo rolling >"$work/status"; : >"$work/failed"
    return 0
  fi
  if [ -z "$failed" ] && [ ! -s "$work/left" ] && ! smoke; then
    echo "smoke RED: rolling back what this build changed"
    failed="$failed smoke"
    rollback "$last" || true
  fi
  if [ -n "$failed" ]; then
    :
  elif [ -s "$work/left" ]; then
    echo "incomplete: left $(tr '\n' ' ' <"$work/left")(not started: out of time budget); /tower/deploy/last-sha stays $last; the next ring resumes: stacks already tagged commit=$head are skipped"
    echo "$failed" >"$work/failed"
    echo incomplete >"$work/status"
    return 1
  fi
  if [ -n "$failed" ]; then
    bisect_state "$last" "$head" "$bgood" "$bbad"
  elif [ -n "$bgood" ] && [ "$head" != "$bbad" ]; then
    jq -nc --arg g "$head" --arg b "$bbad" --argjson k "$bbuilds" --arg t "$btried" \
      '{good: $g, bad: $b, builds: $k, head_tried_sha: $t, reason: "a midpoint deployed green: last-sha moved to it, only the rest is suspect"}' >"$work/bisect"
  else
    echo null >"$work/bisect"  # green and whole (or the last step of a bisection): no bisection, no culprit
  fi
  if [ -z "$failed" ] && [ -s "$work/dirty" ]; then
    failed="$failed dirty:$(tr '\n' ',' <"$work/dirty")"
  fi
  if [ -z "$failed" ]; then
    aws ssm put-parameter --name /tower/deploy/last-sha --type String --overwrite --value "$head" >/dev/null \
      || failed="$failed record:last-sha"
  else
    echo "failed:$failed; /tower/deploy/last-sha stays $last, so the next ring deploys $head again"
  fi
  echo "$failed" >"$work/failed"
  test -z "$failed"
}

# DEP-WATCHDOG: ANY exit records an end. The build writes last-build at its START (status in_progress, the current step, updated at
# each step) and, whatever happens, a failed record with the failing step and the last 40 lines when it leaves without having
# recorded its outcome: an error under set, SIGTERM/INT/HUP, or the script's own hard deadline (DEPLOY_HARD_S, default the
# budget + 240 s from CODEBUILD_START_TIME, less than the project's timeout, which kills with no chance to record). A build that
# is killed anyway is told by the service from the stale `updated` (autodeploy.py, deploy.lost_after_s).
children_of() {  # pgrep when the image has procps (CodeBuild), else /proc (the python:slim runner has no procps)
  if command -v pgrep >/dev/null 2>&1; then pgrep -P "$1" 2>/dev/null; return 0; fi
  local stat
  for stat in /proc/[0-9]*/stat; do
    awk -v p="$1" '{ sub(/^.*\) /, ""); if ($2 == p) { split(FILENAME, f, "/"); print f[3] } }' "$stat" 2>/dev/null
  done
}
kill_tree() {  # the job's whole process group first (set -m below gives each background job its own), then any stragglers
  local child
  kill -TERM -- "-$1" 2>/dev/null || true
  for child in $(children_of "$1"); do kill_tree "$child"; done
  kill -TERM "$1" 2>/dev/null || true
}
on_exit() {
  local rc=$? fs why=""
  trap - EXIT TERM INT HUP
  [[ -z "${watch_pid:-}" ]] || kill_tree "$watch_pid"
  if [[ ! -f "$work/recorded" ]]; then
    [[ -z "${dpid:-}" ]] || kill_tree "$dpid"
    why="$(slurp "$work/why")"; [[ -n "$why" ]] || why="${sig:+terminated by SIG$sig}"; [[ -n "$why" ]] || why="exit $rc before the outcome was recorded"
    fs="$(awk -F'\t' '$2 == "running" {n = $1} END {print n}' "$work/steps" 2>/dev/null)"
    [[ -z "$fs" ]] || step_err "$fs"
    [[ -z "$fs" ]] || { awk -F'\t' -v OFS='\t' -v t="$EPOCHSECONDS" '$2 == "running" {$2 = "failed"; $4 = t} {print}' "$work/steps" >"$work/steps.tmp" && mv "$work/steps.tmp" "$work/steps"; }
    [[ -s "$work/failed_step" ]] || echo "${fs:-before-first-step}" >"$work/failed_step"
    echo "deploy.sh: $why, at step $(<"$work/failed_step")" | tee -a "$output" >&2
    : >"$work/recorded"
    head="$(slurp "$work/head" || echo "$head0")"
    record_tail_lines=40 record failed "$head" "step:$(<"$work/failed_step")" || true
    [[ $rc -ne 0 ]] || rc=1
  fi
  rm -rf "$work"
  exit "$rc"
}
trap on_exit EXIT
trap 'sig=TERM; exit 143' TERM
trap 'sig=INT; exit 130' INT
trap 'sig=HUP; exit 129' HUP
hard="${DEPLOY_HARD_S:-$(( ${DEPLOY_BUDGET_S:-1080} + 240 ))}"; zero="$started"; [[ -n "${CODEBUILD_START_TIME:-}" ]] && zero=$((CODEBUILD_START_TIME / 1000))
left_s=$(( hard - (${DEPLOY_NOW:-$EPOCHSECONDS} - zero) )); (( left_s >= 1 )) || left_s=1
set -m  # each background job below gets its own process group, so kill_tree ends a hung stack deploy with all its children
( sleep "$left_s"; echo "hard deadline ${hard}s exceeded (DEPLOY_HARD_S)" >"$work/why"; kill -TERM $$ ) >/dev/null 2>&1 &
watch_pid=$!
progress  # the build is in_progress from now on
{ deploy 2>&1 | tee "$output"; echo "${PIPESTATUS[0]}" >"$work/code"; } &
dpid=$!
wait "$dpid"
code="$(slurp "$work/code" || echo 1)"
head="$(slurp "$work/head" || echo "$head0")"
read -r -a failed <<<"$(slurp "$work/failed")"
if [[ "$(slurp "$work/status")" == incomplete ]]; then
  status=incomplete
elif [[ $code -ne 0 ]]; then
  status=failed
elif [[ "$(slurp "$work/status")" == nothing_new ]]; then
  status=nothing_new
elif [[ "$(slurp "$work/status")" == rolling ]]; then
  status=rolling  # SLOW-PATH-NO-ROLLOUT-WAIT: ended, its stacks rolling out: not deployed until the next build verifies them
else
  status=succeeded
fi
record "$status" "$head" ${failed[@]+"${failed[@]}"} || echo "could not record /tower/deploy/last-build" >&2
: >"$work/recorded"
exit "$code"
