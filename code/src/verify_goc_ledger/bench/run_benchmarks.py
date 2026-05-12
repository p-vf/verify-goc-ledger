import os
from pathlib import Path
import sys
import argparse

from test_git_cli import verify_repo

def main():
    parser = argparse.ArgumentParser(prog="generate", description="Generates a repository that contains an append-only log representing a GOC-Ledger")
    parser.add_argument("-p", "--stat-prefix", help="set prefix of profile output", default="")
    parser.add_argument("benches", nargs="*", help="specify what benchmarks to run")
    args = parser.parse_args()
    stat_prefix = args.stat_prefix
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
        for e in sorted(os.listdir(test_dir_full)):
            if not os.path.isdir(test_dir_full/e):
                continue
            print(f"running {e}")
            # Run testcase
            verify_repo(str(test_dir_full / e), test_dir_full / (stat_prefix + e + ".stats"), False)

if __name__ == "__main__":
    main()