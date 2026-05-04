import os
from pathlib import Path
import glob
import filecmp
import sys

from common.misc import bcolors
from test_git_cli import verify_repo

def main():
    specified_tests = set(sys.argv[1:])
    run_all_tests = False
    if len(specified_tests) == 0:
        run_all_tests = True
    testcase_dir = Path("./testcases")
    no_passed_testcases = 0
    no_failed_testcases = 0
    for test_dir in os.listdir(testcase_dir):
        if not run_all_tests:
            if test_dir not in specified_tests:
                continue
            else:
                specified_tests.remove(test_dir)
        test_dir_full = testcase_dir / test_dir
        print(test_dir_full)
        assert os.path.isdir(test_dir_full)
        print(f"running testcase '{test_dir}':")
        try:
            for e in os.listdir(test_dir_full):
                if os.path.isdir(e):
                    # Run testcase
                    verify_repo(str(test_dir_full / e), False, True)
        except Exception as e:
            import traceback
            print(f"exception raised: \n{str.join("", traceback.format_tb(e.__traceback__))}")
            no_failed_testcases += 1
            continue

        print("comparing files:")
        successful = True
        for e in glob.glob(str(test_dir_full) + "/expected_*"):
            p = Path(e)
            assert p.name.startswith("expected_")
            basename = p.name.removeprefix("expected_")
            file = test_dir_full / basename
            print(e, "with", file)
            if os.path.exists(file):
                # TODO diff the files here
                if filecmp.cmp(file, e, False):
                    # yay!
                    print("files equal, yay!")
                else:
                    # nay :(
                    print(bcolors.FAIL + "files differ" + bcolors.ENDC)
                    successful = False
                pass
            else:
                assert False, "unreachable"
        if successful:
            no_passed_testcases += 1
        else:
            no_failed_testcases += 1
    print("==== TEST RESULTS ====")
    if len(specified_tests) > 0:
        print(f"WARNING: the specified tests {specified_tests} weren't found")
    print(f"passed: {no_passed_testcases}, failed: {no_failed_testcases}")
    if no_failed_testcases == 0:
        print("all tests passed, hurray!")
    else:
        exit(1)

if __name__ == "__main__":
    main()