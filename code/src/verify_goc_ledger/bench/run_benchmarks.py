import os
from pathlib import Path
import argparse
from typing import Any
import csv

from test_git_cli import verify_repo

def main():
    parser = argparse.ArgumentParser(prog="run_benchmarks", description="Runs Benchmarks")
    parser.add_argument("-p", "--stat-prefix", help="set prefix of profile output", default="")
    parser.add_argument("--profile", action=argparse.BooleanOptionalAction, help="profile output", default=False)
    parser.add_argument("--summary-cache", action=argparse.BooleanOptionalAction, help="run using summary cache", default=True)
    parser.add_argument("benches", nargs="*", help="specify what benchmarks to run")
    args = parser.parse_args()
    profile_output: bool = args.profile
    stat_prefix = args.stat_prefix
    summary_cache = args.summary_cache
    print(f"summary_cache: {summary_cache}")
    specified_tests = args.benches
    run_all_tests = False
    if len(specified_tests) == 0:
        run_all_tests = True
    testcase_dir = Path("./benchmarks")
    for test_dir in os.listdir(testcase_dir):
        if not run_all_tests:
            if test_dir not in specified_tests:
                continue
            else:
                specified_tests.remove(test_dir)
        test_dir_full = testcase_dir / test_dir
        print(test_dir_full)
        assert os.path.isdir(test_dir_full)
        print(f"running benchmark '{test_dir}':")
        rows: list[dict[str, Any]] = []
        fieldnames: list[str] = []
        for e in sorted(os.listdir(test_dir_full)):
            if not os.path.isdir(test_dir_full/e):
                continue
            print(f"running {e}")
            # Run benchmark
            if profile_output:
                new_row = verify_repo(str(test_dir_full / e), test_dir_full / (stat_prefix + e + ".stats"), None, test_dir_full / (stat_prefix + e + ".csv"), summary_cache, True)
            else:
                new_row = verify_repo(str(test_dir_full / e), None, None, test_dir_full / (stat_prefix + e + ".csv"), summary_cache, True)
            assert new_row is not None
            new_row["NAME"] = e
            for fieldname in new_row:
                if fieldname not in fieldnames:
                    fieldnames.append(fieldname)
            rows.append(new_row)
        with open(test_dir_full/(stat_prefix + "perf.csv"), "w+") as csvfile:
            w = csv.DictWriter(csvfile, fieldnames)
            w.writeheader()
            w.writerows(rows)
        print(f"performance statistics saved to {test_dir_full/(stat_prefix + "perf.csv")}")

if __name__ == "__main__":
    main()