#!/usr/bin/env bash
# b34: auto-sync local master to GitHub (private repo). Safe to run anytime:
# pushes only when local is ahead; never force, never touches remote history.
set -u
cd /home/ai/hermes-trading || exit 1
TOK=$(cat .git_token 2>/dev/null) || { echo "$(date -u +%FT%TZ) no token"; exit 1; }
git -c credential.helper='!f() { echo "username=x-access-token"; echo "password='"$TOK"'"; }; f' \
    push origin master >> logs/git_sync.log 2>&1
rc=$?
echo "$(date -u +%FT%TZ) push rc=$rc $(git rev-parse --short HEAD) ahead=$(git rev-list --count origin/master..HEAD 2>/dev/null || echo '?')" >> logs/git_sync.log
exit $rc
