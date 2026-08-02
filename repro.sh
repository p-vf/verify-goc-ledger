#!/usr/bin/bash
# This script reproduces the results detailed in the report.

# === DEPENDENCIES ===
# To run this script, uv must be installed, see https://docs.astral.sh/uv/getting-started/installation/#installation-methods .
# Additionally, the command ssh-keygen must be available and git must be installed.
# The tests were run with git version 2.43.0 and openssh-client version 1:9.6p1-3ubuntu13.18

cd code
echo === running unittests ===
uv run generate_testcases reset >/dev/null
if [ $? -ne 0 ]; then
    echo test generation failed.. terminating the script
    exit 1
fi
uv run run_testcases >/dev/null
if [ $? -eq 0 ]; then
    echo all tests ran successfully!
else
    echo some tests failed.. terminating the script
    exit 1
fi

echo "=== running storage benchmark (takes a while) ==="
yes | uv run storage_benchmark -o ../storage_bench_results/ >/dev/null
if [ $? -eq 0 ]; then
    echo storage benchmark successful!
else
    echo storage benchmark failed.. terminating the script
    exit 1
fi

echo "=== generating performance benchmark (takes a while) ==="
yes | uv run generate_benchmarks >/dev/null
if [ $? -eq 0 ]; then
    echo generated benchmark successfully!
else
    echo some tests failed.. terminating the script
    exit 1
fi
echo === running performance benchmarks ===
uv run run_benchmarks -p "Verification without Summary Cache" --no-summary-cache
if [ $? -ne 0 ]; then
    echo performance benchmark failed.. terminating the script
    exit 1
fi
uv run run_benchmarks -p "Verification with Summary Cache"
if [ $? -ne 0 ]; then
    echo performance benchmark failed.. terminating the script
    exit 1
fi
echo === visualizing performance benchmark results ===
uv run visualize_benchmarks --output-dir ../performance_bench_results/
if [ $? -ne 0 ]; then
    echo visualizing the benchmarks failed.. terminating the script
    exit 1
fi
echo === reproduction complete ===
echo generated figures: ./performance_bench_results/valid_pareto_ack_delayed/
echo csv of storage benchmark results: ./storage_bench_results/results.csv
