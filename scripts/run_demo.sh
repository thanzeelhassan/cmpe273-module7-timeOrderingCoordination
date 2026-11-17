#!/usr/bin/env bash
# Runs the three scenarios and writes the terminal output to logs/.
set -eu
cd "$(dirname "$0")/.."
PY="${PYTHON:-python3}"
mkdir -p logs

"$PY" -u demo.py 1 | tee logs/1_versioned_event_ordering.log
"$PY" -u demo.py 2 | tee logs/2_missing_event.log
"$PY" -u demo.py 3 | tee logs/3_stale_worker_fencing.log

echo
echo "Done. See logs/"
