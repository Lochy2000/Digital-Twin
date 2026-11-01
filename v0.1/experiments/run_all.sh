#!/bin/sh
# Runs every experiment in order, one at a time (they share the machine). About an hour.
# Results: experiments/results/*.csv, console output in experiments/results/logs/.
cd "$(dirname "$0")/.." || exit 1
L=experiments/results/logs
mkdir -p $L
for e in "e1_data_quality.py" "e2_e3_load.py e2" "e2_e3_load.py e2b" "e2_e3_load.py e2c" "e2_e3_load.py e3" "e4_resilience.py" \
         "e6_security.py" "e7_onboarding.py" "e5_storage.py"; do
  set -- $e
  name=$(echo "$e" | tr ' ' '_' | sed 's/\.py//')
  echo "=== $e  $(date -u +%H:%M:%S)"
  python3 experiments/$e > "$L/$name.txt" 2>&1 || echo "    FAILED (see $L/$name.txt)"
done
python3 experiments/figures.py
echo "=== done $(date -u +%H:%M:%S)"
