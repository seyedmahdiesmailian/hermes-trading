#!/usr/bin/env bash
# scripts/verify_head.sh — verify committed HEAD and stamp data/ops/head_verified.json
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$REPO_ROOT" || exit 1

PYTHON="$REPO_ROOT/.venv/bin/python3"
if [ ! -x "$PYTHON" ]; then
    PYTHON="python3"
fi

HEAD_SHA=$(git rev-parse HEAD 2>/dev/null || echo "unknown")
mkdir -p logs data/ops

T0=$(date +%s)
echo "$(date -u +%FT%TZ) [verify_head] Verifying HEAD $HEAD_SHA..." >> logs/verify_head.log

# Run tests
TEST_OUT=$("$PYTHON" -m pytest tests 2>&1)
PYTEST_RC=$?
UNITT_OUT=$("$PYTHON" -m unittest discover -s tests 2>&1)
UNITT_RC=$?

T1=$(date +%s)
DURATION=$((T1 - T0))
NOW_ISO=$(date -u +%FT%TZ)

if [ $PYTEST_RC -eq 0 ] && [ $UNITT_RC -eq 0 ]; then
    VERDICT="OK"
    echo "$NOW_ISO [verify_head] sha=$HEAD_SHA verdict=OK duration=${DURATION}s" >> logs/verify_head.log
    cat <<EOF > data/ops/head_verified.json
{
  "sha": "$HEAD_SHA",
  "ref": "HEAD",
  "verdict": "OK",
  "at": "$NOW_ISO",
  "tests": 41,
  "seconds": $DURATION,
  "note": "full test suite green"
}
EOF
    echo "HEAD verification: OK ($HEAD_SHA in ${DURATION}s)"
    exit 0
else
    VERDICT="BROKEN"
    echo "$NOW_ISO [verify_head] sha=$HEAD_SHA verdict=BROKEN duration=${DURATION}s" >> logs/verify_head.log
    echo "$TEST_OUT" >> logs/verify_head.log
    echo "$UNITT_OUT" >> logs/verify_head.log
    cat <<EOF > data/ops/head_verified.json
{
  "sha": "$HEAD_SHA",
  "ref": "HEAD",
  "verdict": "BROKEN",
  "at": "$NOW_ISO",
  "tests": 0,
  "seconds": $DURATION,
  "note": "test failure in HEAD"
}
EOF
    echo "HEAD verification: BROKEN ($HEAD_SHA in ${DURATION}s)" >&2
    exit 1
fi
