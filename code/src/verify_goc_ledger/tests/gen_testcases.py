from pathlib import Path
import os
from common.git_utils import Repo, add_as_commit_plumbing
from common.misc import generate_human_names, write_verification_output
import sys
import shutil

def main():
    # hacky way to not have to add the calls manually:
    # global_objs = globals()
    # for i in global_objs:
    #     if i.startswith("generate_testcase"):
    #         global_objs[i]()

    if "reset" in sys.argv:
        shutil.rmtree("./testcases/")
    

    generate_testcase1()
    generate_testcase2()
    generate_testcase3()
    generate_testcase4()
    generate_testcase5()
    generate_testcase6()
    generate_testcase7()
    generate_testcase8()
    generate_testcase9()
    #generate_testcase10() # TODO fix this (allowing empty delta state by add_as_commit_plumbing)

def generate_testcase1():
    test_dir = Path("./testcases/relevant_dependencies")
    if os.path.exists(test_dir):
        print(f"directory {test_dir} exists already, not generating.")
        return
    
    a, b = generate_human_names(2)
    repo = Repo(str(test_dir/"db"))
    repo.create_repo()
    date = 1774010000
    a1 = add_as_commit_plumbing(repo, [], a, date, created=100)
    b1 = add_as_commit_plumbing(repo, [], b, date + 1, created=100)
    a2 = add_as_commit_plumbing(repo, [a1, b1], a, date + 2, destroyed=50)

    valid_commits = [a1, b1]
    invalid_commits = [a2]

    write_verification_output(test_dir, list(map(lambda x: x.encode(), valid_commits)), list(map(lambda x: x.encode(), invalid_commits)), "expected_")

def generate_testcase2():
    test_dir = Path("./testcases/delta_state_minimality_1")
    if os.path.exists(test_dir):
        print(f"directory {test_dir} exists already, not generating.")
        return
    
    a, b, c = generate_human_names(3)
    repo = Repo(str(test_dir/"db"))
    repo.create_repo()
    date = 1774010000
    a1 = add_as_commit_plumbing(repo, [], a, date, created=100, destroyed=0)
    c1 = add_as_commit_plumbing(repo, [], c, date + 1, created=0)
    b1 = add_as_commit_plumbing(repo, [], b, date + 2, created=100)
    # TODO add commits to generate empty acked/given dict

    valid_commits = [b1]
    invalid_commits = [a1, c1]

    write_verification_output(test_dir, list(map(lambda x: x.encode(), valid_commits)), list(map(lambda x: x.encode(), invalid_commits)), "expected_")

def generate_testcase3():
    test_dir = Path("./testcases/delta_state_minimality_2")
    if os.path.exists(test_dir):
        print(f"directory {test_dir} exists already, not generating.")
        return
    
    a, b, c, d = generate_human_names(4)
    repo = Repo(str(test_dir/"db"))
    repo.create_repo()
    date = 1774010000
    a1 = add_as_commit_plumbing(repo, [], a, date, created=100, msg="a1")
    b1 = add_as_commit_plumbing(repo, [], b, date + 1, created=100, msg="b1")
    c1 = add_as_commit_plumbing(repo, [], c, date + 2, created=100, msg="c1")
    d1 = add_as_commit_plumbing(repo, [], d, date + 3, created=100, destroyed=100, msg="d1")
    b2 = add_as_commit_plumbing(repo, [b1, a1], b, date + 5, given={a.encode(): 10}, msg="b2")
    a2 = add_as_commit_plumbing(repo, [a1, b2], a, date + 6, acked={b.encode(): 10}, msg="a2")
    
    b3 = add_as_commit_plumbing(repo, [b2, a1], b, date + 7, given={a.encode(): 10}, msg="b3")
    a3 = add_as_commit_plumbing(repo, [a2, b1], a, date + 8, acked={b.encode(): 10}, msg="a3")
    c2 = add_as_commit_plumbing(repo, [c1], c, date + 9, created=100, msg="c2")
    d2 = add_as_commit_plumbing(repo, [d1], d, date + 10, destroyed=100, msg="d2")

    valid_commits = [a1, b1, c1, d1, b2, a2]
    invalid_commits = [b3, a3, c2, d2]

    write_verification_output(test_dir, list(map(lambda x: x.encode(), valid_commits)), list(map(lambda x: x.encode(), invalid_commits)), "expected_")
    
def generate_testcase4():
    test_dir = Path("./testcases/delta_state_valid_acks")
    if os.path.exists(test_dir):
        print(f"directory {test_dir} exists already, not generating.")
        return
    
    a, b = generate_human_names(2)
    repo = Repo(str(test_dir/"db"))
    repo.create_repo()
    date = 1774010000
    a1 = add_as_commit_plumbing(repo, [], a, date, created=100)
    b1 = add_as_commit_plumbing(repo, [], b, date + 2, created=100)
    b2 = add_as_commit_plumbing(repo, [b1, a1], b, date + 3, given={a.encode(): 100})
    b3 = add_as_commit_plumbing(repo, [b2, a1], b, date + 4, acked={a.encode(): 100}) # `b` acks from `a` although it never got anything from `a`
    a2 = add_as_commit_plumbing(repo, [a1, b2], a, date + 5, acked={b.encode(): 120}) # `a` acks too much from `b`

    valid_commits = [a1, b1, b2]
    invalid_commits = [b3, a2]

    write_verification_output(test_dir, list(map(lambda x: x.encode(), valid_commits)), list(map(lambda x: x.encode(), invalid_commits)), "expected_")

def generate_testcase5():
    test_dir = Path("./testcases/delta_state_non_negative_balance_giving")
    if os.path.exists(test_dir):
        print(f"directory {test_dir} exists already, not generating.")
        return
    
    a, b = generate_human_names(2)
    repo = Repo(str(test_dir/"db"))
    repo.create_repo()
    date = 1774010000
    a1 = add_as_commit_plumbing(repo, [], a, date, created=100)
    b1 = add_as_commit_plumbing(repo, [], b, date + 2, created=100)
    a2 = add_as_commit_plumbing(repo, [a1, b1], a, date + 5, given={b.encode(): 120})

    valid_commits = [a1, b1]
    invalid_commits = [a2]

    write_verification_output(test_dir, list(map(lambda x: x.encode(), valid_commits)), list(map(lambda x: x.encode(), invalid_commits)), "expected_")

def generate_testcase6():
    # TODO maybe add more complicated testcase to check if balance gets calculated correctly or smthn
    test_dir = Path("./testcases/delta_state_non_negative_balance_destroying")
    if os.path.exists(test_dir):
        print(f"directory {test_dir} exists already, not generating.")
        return
    
    a, b = generate_human_names(2)
    repo = Repo(str(test_dir/"db"))
    repo.create_repo()
    date = 1774010000
    a1 = add_as_commit_plumbing(repo, [], a, date, created=100)
    b1 = add_as_commit_plumbing(repo, [], b, date + 2, created=100)
    a2 = add_as_commit_plumbing(repo, [a1, b1], a, date + 5, destroyed=101)

    valid_commits = [a1, b1]
    invalid_commits = [a2]

    write_verification_output(test_dir, list(map(lambda x: x.encode(), valid_commits)), list(map(lambda x: x.encode(), invalid_commits)), "expected_")

def generate_testcase7():
    test_dir = Path("./testcases/commit_date_non_decreasing")
    if os.path.exists(test_dir):
        print(f"directory {test_dir} exists already, not generating.")
        return
    
    a, = generate_human_names(1)
    repo = Repo(str(test_dir/"db"))
    repo.create_repo()
    date = 1774010000
    a1 = add_as_commit_plumbing(repo, [], a, date, created=100)
    a2 = add_as_commit_plumbing(repo, [a1], a, date, destroyed=100)
    a3 = add_as_commit_plumbing(repo, [a2], a, date-1, created=101)

    valid_commits = [a1, a2]
    invalid_commits = [a3]

    write_verification_output(test_dir, list(map(lambda x: x.encode(), valid_commits)), list(map(lambda x: x.encode(), invalid_commits)), "expected_")

def generate_testcase8():
    test_dir = Path("./testcases/misc_1")
    if os.path.exists(test_dir):
        print(f"directory {test_dir} exists already, not generating.")
        return
    
    a, b, c = generate_human_names(3)
    repo = Repo(str(test_dir/"db"))
    repo.create_repo()
    date = 1774010000
    c1 = add_as_commit_plumbing(repo, [], c, date + 2, created=100, msg="c1")
    
    c2 = add_as_commit_plumbing(repo, [c1], c, date + 9, created=100, msg="c2")

    valid_commits = [c1]
    invalid_commits = [c2]

    write_verification_output(test_dir, list(map(lambda x: x.encode(), valid_commits)), list(map(lambda x: x.encode(), invalid_commits)), "expected_")

def generate_testcase9():
    test_dir = Path("./testcases/necessary_dependencies")
    if os.path.exists(test_dir):
        print(f"directory {test_dir} exists already, not generating.")
        return
    
    a, b = generate_human_names(2)
    repo = Repo(str(test_dir/"db"))
    repo.create_repo()
    date = 1774010000
    a1 = add_as_commit_plumbing(repo, [], a, date, created=100)
    b1 = add_as_commit_plumbing(repo, [], b, date+1, created=100)
    b2 = add_as_commit_plumbing(repo, [b1], b, date+1, given={a.encode(): 10})

    valid_commits = [a1, b1]
    invalid_commits = [b2]

    write_verification_output(test_dir, list(map(lambda x: x.encode(), valid_commits)), list(map(lambda x: x.encode(), invalid_commits)), "expected_")

def generate_testcase10():
    test_dir = Path("./testcases/delta_state_empty")
    if os.path.exists(test_dir):
        print(f"directory {test_dir} exists already, not generating.")
        return
    
    a, b = generate_human_names(2)
    repo = Repo(str(test_dir/"db"))
    repo.create_repo()
    date = 1774010000
    a1 = add_as_commit_plumbing(repo, [], a, date, created=100)
    b1 = add_as_commit_plumbing(repo, [], b, date+1, created=100)
    b2 = add_as_commit_plumbing(repo, [b1], b, date+1)

    valid_commits = [a1, b1]
    invalid_commits = [b2]

    write_verification_output(test_dir, list(map(lambda x: x.encode(), valid_commits)), list(map(lambda x: x.encode(), invalid_commits)), "expected_")

if __name__ == "__main__":
    main()