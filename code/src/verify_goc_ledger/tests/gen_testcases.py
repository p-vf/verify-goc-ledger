from pathlib import Path
import os
from git_utils import Repo, add_as_commit_plumbing
from common.misc import generate_human_names, write_verification_output
from common.account import Account

def main():
    test_dir = Path("./testcases/test1")
    if os.path.exists(test_dir):
        print(f"directory {test_dir} exists already, aborting.")
        exit(1)
    
    a, b = generate_human_names(2)
    repo = Repo(str(test_dir/"db"))
    repo.create_repo()
    date = 1774010000
    a1 = add_as_commit_plumbing(repo, [], a, date, created=100, destroyed=None, acked=None, given=None)
    b1 = add_as_commit_plumbing(repo, [], b, date + 1, created=100, destroyed=None, acked=None, given=None)
    a2 = add_as_commit_plumbing(repo, [a1, b1], a, date + 2, created=None, destroyed=50, acked=None, given=None)

    valid_commits = [a1, b1]
    invalid_commits = [a2]

    write_verification_output(test_dir, list(map(lambda x: x.encode(), valid_commits)), list(map(lambda x: x.encode(), invalid_commits)), "expected_")
    return

if __name__ == "__main__":
    main()