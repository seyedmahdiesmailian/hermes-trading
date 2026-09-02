#!/usr/bin/env bash
# b34: auto-sync local master to GitHub (private repo). Safe to run anytime:
# pushes only when local is ahead; never force, never touches remote history.
#
# b45: NEVER push an UNVERIFIED HEAD. 43c5f52 and 920ed0d shipped commits
# that a clean checkout could not run (untracked module / tests staged
# without their source fixes) — cron pushed them anyway, GitHub inherited
# the breakage, and a restore-from-remote would have restored a dead tree.
# Since b50, scripts/verify_head.sh runs the FULL suite inside HEAD and
# stamps data/ops/head_verified.json; this script asks that stamp before
# every push (engines/head_verify.py push-gate).
#
# Fail-open by design on a MISSING or STALE (>1h) stamp: a dead verifier
# must not freeze pushes forever — backups depend on this cron. But a FRESH
# verdict is law: BROKEN, or OK-for-a-different-sha, blocks the push and
# says so loudly in the log. The reason is always logged, so "verified good"
# and "pushed unverified" are never the same line (b49 posture).
set -u
cd /home/ai/hermes-trading || exit 1

# b61: GIT_TOKEN_FILE is a documented .env.example key that NOTHING read —
# git_sync hardcoded `cat .git_token`, so a fresh server was handed a knob
# that does nothing (stale deploy contract). Now honored: source .env with
# the same set -a pattern as hermes_cron.sh, and keep .git_token as the
# default so behaviour is IDENTICAL when the key is unset (the b45
# end-to-end test runs this script in a throwaway repo with no .env).
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

# Nothing to push? Stay silent (the gate must not spam on idle ticks).
AHEAD=$(git rev-list --count origin/master..HEAD 2>/dev/null || echo "?")
if [ "$AHEAD" = "0" ]; then
  exit 0
fi

GATE=$(timeout 30 python3 engines/head_verify.py push-gate 2>/dev/null)
GATE_RC=$?
case "$GATE_RC" in
  0) : ;;                              # push allowed (reason in $GATE)
  1) # blocked — loud in the log; the ops page already came from
     # verify_head.sh itself (one writer, one voice — b40 convention), so
     # git_sync must not re-page every 15 min on the same broken HEAD.
     echo "$(date -u +%FT%TZ) PUSH BLOCKED by b45 gate: $GATE" >> logs/git_sync.log
     exit 0
     ;;
  *) # gate itself broken (timeout/crash): fail-open, but say so
     echo "$(date -u +%FT%TZ) b45 gate rc=$GATE_RC (verifier broken?) — fail-open push" >> logs/git_sync.log
     ;;
esac

TOK=$(cat "${GIT_TOKEN_FILE:-.git_token}" 2>/dev/null) || { echo "$(date -u +%FT%TZ) no token"; exit 1; }
git -c credential.helper='!f() { echo "username=x-access-token"; echo "password='"$TOK"'"; }; f' \
    push origin master >> logs/git_sync.log 2>&1
rc=$?
echo "$(date -u +%FT%TZ) push rc=$rc $(git rev-parse --short HEAD) ahead=$AHEAD gate=\"$GATE\"" >> logs/git_sync.log
exit $rc
