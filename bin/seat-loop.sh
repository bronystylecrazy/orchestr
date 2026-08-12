#!/bin/sh
# orchestr seat runner — one fresh session per ticket, gate-then-spawn.
#
# Usage: seat-loop.sh <profile[,profile2,...]> <bot-user> <tier> [--once] [--interval N] [--dangerous]
#   profile   Claude profile name(s) under ~/.local/share/claude-profiles/,
#             in failover order (first not cooling down is used)
#   bot-user  GitLab bot identity; its token line must exist in ~/.config/orchestr/tokens
#   tier      frontier | standard | mechanical  (selects the has_work pre-filter)
#   --once      run a single gated tick, then exit (testing / cron mode)
#   --watch/--no-watch  live-render session activity (default: on when stdout is a TTY)
#   --interval  poll seconds (default 10; events-gated — a full queue check runs every 6th tick)
#   --directed  concierge mode: wake ONLY for human-assigned work (no pull queues)
#   --no-update disable post-session self-update (plugin caches + git pull)
#   --model     pin the session model (e.g. sonnet) instead of the profile default
#   --safe      DISABLE the default --dangerously-skip-permissions and rely on the
#               profile's settings.json permissions instead. NOTE (verified): deny
#               rules do NOT hold under skip-permissions — the default mode's only
#               fences are the skill's stay-in-your-worktree rule and the bots'
#               limited GitLab roles.
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
SELF="$0"; ORIG_ARGS="$*"
SELF_STAMP=$(stat -f %m "$SELF" 2>/dev/null || stat -c %Y "$SELF" 2>/dev/null || echo 0)
PROFILES=$(echo "${1:?profile}" | tr ',' ' '); BOT="${2:?bot-user}"; TIER="${3:?tier}"; shift 3
ONCE=0; INTERVAL=10; DANGEROUS="--dangerously-skip-permissions"; MODEL=""
WATCH=0; [ -t 1 ] && WATCH=1   # live session rendering when stdout is a terminal
while [ $# -gt 0 ]; do case "$1" in
  --once) ONCE=1 ;; --interval) INTERVAL="$2"; shift ;;
  --model) MODEL="$2"; shift ;;
  --watch) WATCH=1 ;; --no-watch) WATCH=0 ;;
  --safe) DANGEROUS="" ;;
  --directed) DIRECTED=1 ;;
  --no-update) AUTOUPDATE=0 ;;
  --dangerous) DANGEROUS="--dangerously-skip-permissions" ;;
esac; shift; done
: "${AUTOUPDATE:=1}"; : "${DIRECTED:=0}"
PROMPT="/orchestr:next-ticket"; [ "$DIRECTED" -eq 1 ] && PROMPT="/orchestr:next-ticket directed-only"

GITLAB_HOST=$(cat "$CFG/gitlab-host" 2>/dev/null) || { echo "missing $CFG/gitlab-host"; exit 1; }
GITLAB_TOKEN=$(awk -v b="$BOT" '$1==b{print $2}' "$CFG/tokens")
[ -n "$GITLAB_TOKEN" ] || { echo "no token for $BOT in $CFG/tokens"; exit 1; }
[ -s "$CFG/projects" ] || { echo "missing $CFG/projects"; exit 1; }
export GITLAB_HOST GITLAB_TOKEN
mkdir -p "$CFG/ledger" "$CFG/logs" "$CFG/cooldown" "$CFG/events-cursor"

# events pre-gate: one API call answers "did anything happen since last look?"
# Label-only edits emit no event (route posts a 'routed:' note to compensate),
# so a full queue check still runs every 6th tick as the floor.
fresh_events() {  # $1=project dir; cursor keyed per bot+project
  key="$BOT-$(basename "$1")"
  latest=$(cd "$1" && glab api "projects/:id/events?per_page=1" 2>/dev/null | \
    python3 -c "import json,sys
try: print(json.load(sys.stdin)[0]['created_at'])
except Exception: print('')")
  [ -n "$latest" ] || return 0   # API hiccup -> fail open to a full check
  cur=$(cat "$CFG/events-cursor/$key" 2>/dev/null || echo "")
  printf '%s' "$latest" > "$CFG/events-cursor/$key"
  [ "$latest" != "$cur" ]
}
LOG="$CFG/logs/$BOT.log"
log() { echo "$(date -u +%FT%TZ) $*" | tee -a "$LOG"; }

# --- gate: does this tier have work in this project dir? (pre-filter only —
# false positives cost one session; a MISSING queue here means the seat never
# wakes for that work. glab quirk: mr list wants -F json, issue list wants -O json.)
nonempty() { [ "$(printf %s "$1" | head -c 3)" != "[]" ] && [ -n "$1" ]; }
unassigned() {  # stdin: issue-list JSON; true if any issue has no assignee
  python3 -c 'import json,sys
try: d=json.load(sys.stdin)
except Exception: sys.exit(1)
sys.exit(0 if any(not i.get("assignees") for i in d) else 1)'
}
has_work() {
  _mine=$(glab mr list --label changes-requested -F json 2>/dev/null | grep -c "\"username\":\"$BOT\"") || _mine=0
  [ "$_mine" -gt 0 ] && return 0
  # directed work: human assigned this bot (label still on = not yet claimed)
  nonempty "$(glab issue list --assignee "$BOT" --label ready-for-agent -O json 2>/dev/null)" && return 0
  glab api "projects/:id/merge_requests?state=opened&reviewer_username=$BOT" 2>/dev/null | python3 -c "
import json,sys
try: mrs=json.load(sys.stdin)
except Exception: sys.exit(1)
sys.exit(0 if any('changes-requested' not in m.get('labels',[]) for m in mrs) else 1)" && return 0
  [ "$DIRECTED" -eq 1 ] && return 1   # directed-only seats never wake for pull queues
  case "$TIER" in
    mechanical)
      glab issue list --label needs-peer-check -O json 2>/dev/null | unassigned && return 0
      glab issue list --label ready-for-agent --label tier:mechanical -O json 2>/dev/null | unassigned && return 0 ;;
    standard)
      nonempty "$(glab mr list --label review:light -F json 2>/dev/null)" && return 0
      glab issue list --label ready-for-agent --label tier:standard -O json 2>/dev/null | unassigned && return 0
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
      # review:light only when aged >4h (seat economy — fresh light reviews are standard's)
      glab mr list --label review:light -F json 2>/dev/null | python3 -c "
import json,sys,datetime
now=datetime.datetime.now(datetime.timezone.utc)
try: mrs=json.load(sys.stdin)
except Exception: sys.exit(1)
for m in mrs:
    age=(now-datetime.datetime.fromisoformat(m['created_at'].replace('Z','+00:00'))).total_seconds()
    if age>14400: sys.exit(0)
sys.exit(1)" && return 0
      nonempty "$(glab mr list --merged --label needs-frontier-review -F json 2>/dev/null)" && return 0
      nonempty "$(glab issue list --label needs-triage -O json 2>/dev/null)" && return 0
      glab issue list --label ready-for-agent --label tier:frontier -O json 2>/dev/null | unassigned && return 0 ;;
  esac
  return 1
}

self_update() {  # post-session: refresh plugin caches + own repo; mtime restart handles the rest
  [ "$AUTOUPDATE" -eq 1 ] || return 0
  for p in $PROFILES; do
    CLAUDE_CONFIG_DIR="$HOME/.local/share/claude-profiles/$p" claude plugin update orchestr@orchestr >/dev/null 2>&1
  done
  repo_root=$(cd "$(dirname "$SELF")/.." && pwd)
  [ -d "$repo_root/.git" ] && git -C "$repo_root" pull -q --ff-only 2>/dev/null
  return 0
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
  if [ "$WATCH" -eq 1 ]; then
    ( cd "$2" && CLAUDE_CONFIG_DIR="$HOME/.local/share/claude-profiles/$1" \
        claude -p "$PROMPT" --output-format stream-json --verbose $DANGEROUS ${MODEL:+--model "$MODEL"} 2>"$err" \
      | python3 "$(dirname "$0")/session-render.py" "$out" )
  else
    ( cd "$2" && CLAUDE_CONFIG_DIR="$HOME/.local/share/claude-profiles/$1" \
        claude -p "$PROMPT" --output-format json $DANGEROUS ${MODEL:+--model "$MODEL"} >"$out" 2>"$err" )
  fi
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
  # failure detection -> cool this profile so the next tick fails over
  if grep -qiE "oauth|authenticate|please run /login|login required" "$out" "$err" 2>/dev/null; then
    echo $(( $(date +%s) + 3600 )) > "$CFG/cooldown/$1"
    log "profile $1 AUTH FAILURE -> cooling 1h, failing over. Fix: CLAUDE_CONFIG_DIR=\$HOME/.local/share/claude-profiles/$1 claude   (then /login)"
  elif grep -qiE "usage limit|rate limit|over.{0,10}limit" "$out" "$err" 2>/dev/null; then
    echo $(( $(date +%s) + 3600 )) > "$CFG/cooldown/$1"
    log "profile $1 over limit -> cooling 1h (rc=$rc)"
  elif [ $rc -ne 0 ]; then
    log "session rc=$rc (unclassified failure); see stderr head:"; head -c 200 "$err" >>"$LOG"
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
  full=0
  { [ "$tick" -eq 0 ] || [ $(( tick % 6 )) -eq 0 ]; } && full=1   # startup + every ~60s: full check regardless of events
  while IFS= read -r proj; do
    [ -d "$proj" ] || continue
    if [ "$full" -eq 0 ] && ! fresh_events "$proj"; then continue; fi
    if ( cd "$proj" && has_work ); then
      for _try in $PROFILES; do
        prof=$(pick_profile) || { log "all profiles cooling; skipping tick"; break; }
        log "work detected in $proj -> session as $BOT via profile $prof"
        run_session "$prof" "$proj"
        worked=1
        # profile just got cooled by that session (auth/limit)? fail over NOW
        _until=$(cat "$CFG/cooldown/$prof" 2>/dev/null || echo 0)
        [ "$_until" -gt "$(date +%s)" ] || break
        log "immediate failover: $prof cooled mid-tick"
      done
      self_update
      break   # one ticket per tick; next tick re-evaluates all projects
    fi
  done < "$CFG/projects"
  [ "$ONCE" -eq 1 ] && { log "once mode: exiting (worked=$worked)"; exit 0; }
  now_stamp=$(stat -f %m "$SELF" 2>/dev/null || stat -c %Y "$SELF" 2>/dev/null || echo 0)
  if [ "$now_stamp" != "$SELF_STAMP" ]; then
    log "script updated on disk -> restarting self"
    exec /bin/sh "$SELF" $ORIG_ARGS
  fi
  tick=$((tick + 1))
  [ "$tick" -eq 1 ] && [ "$worked" -eq 0 ] && log "idle — queues empty; events-gated ${INTERVAL}s polls, full check ~60s, heartbeat ~15m"
  [ $(( tick % 90 )) -eq 0 ] && log "heartbeat: alive, tick $tick, idle"
  sleep $(( INTERVAL + $(od -An -N1 -tu1 /dev/urandom | tr -d ' ') % 5 ))
done
