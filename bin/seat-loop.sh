#!/bin/sh
# orchestr seat runner — one fresh session per ticket, gate-then-spawn.
#
# Usage: seat-loop.sh <profile[,profile2,...]> <bot-user> <tier> [--once] [--interval N] [--dangerous]
#   profile   Claude profile name(s) under ~/.local/share/claude-profiles/,
#             in failover order (first not cooling down is used)
#   bot-user  GitLab bot identity; its token line must exist in ~/.config/orchestr/tokens
#   tier      frontier | standard | mechanical  (selects the has_work pre-filter)
#   --once      run a single gated tick, then exit (testing / cron mode)
#   --interval  poll seconds (default 60)
#   --dangerous pass --dangerously-skip-permissions to claude (dedicated boxes only;
#               default expects the profile's settings.json allowlist — see
#               templates/seat-permissions.json in this plugin)
#
# Config:
#   ~/.config/orchestr/tokens       lines: "<bot-user> <token>"
#   ~/.config/orchestr/gitlab-host  the GitLab host (one line)
#   ~/.config/orchestr/projects     one local clone path per line
# Output:
#   ~/.config/orchestr/ledger/<profile>.jsonl   per-session usage records
#   ~/.config/orchestr/logs/<bot-user>.log      runner log
#   ~/.config/orchestr/cooldown/<profile>       epoch-until file when over limit

set -u
CFG="$HOME/.config/orchestr"
PROFILES=$(echo "${1:?profile}" | tr ',' ' '); BOT="${2:?bot-user}"; TIER="${3:?tier}"; shift 3
ONCE=0; INTERVAL=60; DANGEROUS=""
while [ $# -gt 0 ]; do case "$1" in
  --once) ONCE=1 ;; --interval) INTERVAL="$2"; shift ;;
  --dangerous) DANGEROUS="--dangerously-skip-permissions" ;;
esac; shift; done

GITLAB_HOST=$(cat "$CFG/gitlab-host" 2>/dev/null) || { echo "missing $CFG/gitlab-host"; exit 1; }
GITLAB_TOKEN=$(awk -v b="$BOT" '$1==b{print $2}' "$CFG/tokens")
[ -n "$GITLAB_TOKEN" ] || { echo "no token for $BOT in $CFG/tokens"; exit 1; }
[ -s "$CFG/projects" ] || { echo "missing $CFG/projects"; exit 1; }
export GITLAB_HOST GITLAB_TOKEN
mkdir -p "$CFG/ledger" "$CFG/logs" "$CFG/cooldown"
LOG="$CFG/logs/$BOT.log"
log() { echo "$(date -u +%FT%TZ) $*" | tee -a "$LOG"; }

# --- gate: does this tier have work in this project dir? (pre-filter only —
# false positives cost one session; a MISSING queue here means the seat never
# wakes for that work. glab quirk: mr list wants -F json, issue list wants -O json.)
nonempty() { [ "$(printf %s "$1" | head -c 3)" != "[]" ] && [ -n "$1" ]; }
has_work() {
  _mine=$(glab mr list --label changes-requested -F json 2>/dev/null | grep -c "\"username\":\"$BOT\"") || _mine=0
  [ "$_mine" -gt 0 ] && return 0
  case "$TIER" in
    mechanical)
      nonempty "$(glab issue list --label needs-peer-check -O json 2>/dev/null)" && return 0
      nonempty "$(glab issue list --label ready-for-agent --label tier:mechanical -O json 2>/dev/null)" && return 0 ;;
    standard)
      nonempty "$(glab mr list --label review:light -F json 2>/dev/null)" && return 0
      nonempty "$(glab issue list --label ready-for-agent --label tier:standard -O json 2>/dev/null)" && return 0
      # aged mechanical (seat economy: >24h unclaimed)
      glab issue list --label ready-for-agent --label tier:mechanical -O json 2>/dev/null | python3 -c "
import json,sys,datetime
now=datetime.datetime.now(datetime.timezone.utc)
try: issues=json.load(sys.stdin)
except Exception: sys.exit(1)
for i in issues:
    if i.get('assignees'): continue
    age=(now-datetime.datetime.fromisoformat(i['created_at'].replace('Z','+00:00'))).total_seconds()
    if age>86400: sys.exit(0)
sys.exit(1)" && return 0 ;;
    frontier)
      nonempty "$(glab mr list --label review:frontier -F json 2>/dev/null)" && return 0
      nonempty "$(glab mr list --label review:light -F json 2>/dev/null)" && return 0
      nonempty "$(glab mr list --merged --label needs-frontier-review -F json 2>/dev/null)" && return 0
      nonempty "$(glab issue list --label needs-triage -O json 2>/dev/null)" && return 0
      nonempty "$(glab issue list --label ready-for-agent --label tier:frontier -O json 2>/dev/null)" && return 0 ;;
  esac
  return 1
}

pick_profile() {  # first profile not cooling down
  now=$(date +%s)
  for p in $PROFILES; do
    until_ts=$(cat "$CFG/cooldown/$p" 2>/dev/null || echo 0)
    [ "$now" -ge "$until_ts" ] && { echo "$p"; return 0; }
  done
  return 1
}

run_session() {  # $1=profile $2=project-dir
  out=$(mktemp); err=$(mktemp)
  ( cd "$2" && CLAUDE_CONFIG_DIR="$HOME/.local/share/claude-profiles/$1" \
      claude -p "/orchestr:next-ticket" --output-format json $DANGEROUS >"$out" 2>"$err" )
  rc=$?
  python3 - "$out" "$1" "$BOT" "$2" >>"$CFG/ledger/$1.jsonl" <<'PY'
import json, sys, datetime
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    d = {"parse_error": True}
u = d.get("usage") or {}
print(json.dumps({
    "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
    "profile": sys.argv[2], "bot": sys.argv[3], "project": sys.argv[4],
    "cost_usd": d.get("total_cost_usd"), "in": u.get("input_tokens"),
    "out": u.get("output_tokens"), "cache_read": u.get("cache_read_input_tokens"),
    "turns": d.get("num_turns"), "dur_ms": d.get("duration_ms"),
    "is_error": d.get("is_error", True),
    "result_head": (d.get("result") or "")[:160]}))
PY
  # over-limit detection -> cool this profile down until the stated reset (fallback 1h)
  if grep -qiE "usage limit|rate limit|over.{0,10}limit" "$out" "$err" 2>/dev/null || [ $rc -ne 0 ]; then
    if grep -qiE "limit" "$out" "$err" 2>/dev/null; then
      echo $(( $(date +%s) + 3600 )) > "$CFG/cooldown/$1"
      log "profile $1 over limit -> cooling 1h (rc=$rc)"
    else
      log "session rc=$rc (not limit-shaped); see $err"
    fi
  fi
  head -c 200 "$out" >>"$LOG"; echo >>"$LOG"
  rm -f "$out" "$err"
}

VERSION=$(sed -n 's/.*"version": "\([^"]*\)".*/\1/p' "$(dirname "$0")/../.claude-plugin/plugin.json" 2>/dev/null || echo "?")
NPROJ=$(grep -c . "$CFG/projects")
log "seat-loop (orchestr $VERSION) bot=$BOT tier=$TIER profiles=[$PROFILES] projects=$NPROJ interval=${INTERVAL}s once=$ONCE"
tick=0
while :; do
  worked=0
  while IFS= read -r proj; do
    [ -d "$proj" ] || continue
    if ( cd "$proj" && has_work ); then
      prof=$(pick_profile) || { log "all profiles cooling; skipping tick"; break; }
      log "work detected in $proj -> session as $BOT via profile $prof"
      run_session "$prof" "$proj"
      worked=1
      break   # one ticket per tick; next tick re-evaluates all projects
    fi
  done < "$CFG/projects"
  [ "$ONCE" -eq 1 ] && { log "once mode: exiting (worked=$worked)"; exit 0; }
  tick=$((tick + 1))
  [ "$tick" -eq 1 ] && [ "$worked" -eq 0 ] && log "idle — queues empty; polling every ~${INTERVAL}s, heartbeat every ~15m"
  [ $(( tick % 15 )) -eq 0 ] && log "heartbeat: alive, tick $tick, idle"
  sleep $(( INTERVAL + $(od -An -N1 -tu1 /dev/urandom | tr -d ' ') % 30 ))
done
