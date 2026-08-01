import os
from pathlib import Path
import glob
import filecmp
import sys
import re

from common.misc import bcolors
from verification.git_cli_verification import verify_repo

def main():
    specified_tests = set(sys.argv[1:])
    if len(specified_tests) == 0:
        test_regex = re.compile(".*") # if no tests specified, run all of them
    else:
        test_regex = re.compile("(" + ")|(".join(specified_tests) + ")")
    testcase_dir = Path("./testcases")
    no_passed_testcases = 0
    no_failed_testcases = 0
    for test_dir in os.listdir(testcase_dir):
        if not test_regex.match(test_dir):
            continue
        test_dir_full = testcase_dir / test_dir
        print(test_dir_full)
        assert os.path.isdir(test_dir_full)
        print(f"running testcase '{test_dir}':")
        for e in os.listdir(test_dir_full):
            if not e.startswith("expected_") and os.path.isfile(test_dir_full/e):
                os.remove(test_dir_full/e)
        try:
            for e in os.listdir(test_dir_full):
                if os.path.isdir(test_dir_full/e):
                    # Run testcase
                    verify_repo(str(test_dir_full / e), None, test_dir_full, None, False, False)
        except Exception as e:
            import traceback
            print(f"exception raised: \n{bcolors.FAIL + str.join("", traceback.format_tb(e.__traceback__)) + bcolors.ENDC}")
            if len(e.args) > 0:
                print(f"exception message: \n{bcolors.WARNING + str(e.args[0]) + bcolors.ENDC}")
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
                    print(bcolors.OKGREEN + "files equal, yay!" + bcolors.ENDC)
                else:
                    # nay :(
                    print(bcolors.FAIL + "files differ" + bcolors.ENDC)
                    successful = False
                pass
            else:
                print(bcolors.FAIL + f"file {file} doesn't exist, test failed." + bcolors.ENDC)
                successful = False
        if successful:
            no_passed_testcases += 1
        else:
            no_failed_testcases += 1
    print("==== TEST RESULTS ====")
    print(f"passed: {no_passed_testcases}, failed: {no_failed_testcases}")
    if no_failed_testcases == 0:
        print(bcolors.OKGREEN + "all tests passed, hurray!" + bcolors.ENDC)
    else:
        print(bcolors.FAIL + "some tests failed :(" + bcolors.ENDC)
        exit(1)

if __name__ == "__main__":
    main()