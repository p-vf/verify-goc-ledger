from pathlib import Path
import os
from common.git_utils import Repo, add_delta_state_as_commit_plumbing, add_fork_proof_as_commit
from common.misc import generate_human_names
import sys
import shutil

def main():
    # hacky way to not have to add the calls manually:
    # global_objs = globals()
    # for i in global_objs:
    #     if i.startswith("generate_testcase"):
    #         global_objs[i]()

    for arg in sys.argv[1:]:
        if arg == "reset":
            if os.path.exists("./testcases/"):
                shutil.rmtree("./testcases/")
            continue
        global_objs = globals()
        funcname = "generate_testcase_" + arg
        if funcname in global_objs:
            global_objs[funcname]()

    generate_testcase_relevant_dependencies()
    generate_testcase_delta_account_minimality_1()
    generate_testcase_delta_account_minimality_2()
    generate_testcase_delta_account_valid_acks()
    generate_testcase_delta_account_non_negative_balance_giving()
    generate_testcase_delta_account_non_negative_balance_destroying()
    generate_testcase_commit_date_non_decreasing()
    generate_testcase_misc_1()
    generate_testcase_necessary_dependencies()
    #generate_testcase_delta_account_empty() # TODO fix this (allowing empty delta state by add_as_commit_plumbing)
    generate_testcase_single_author()
    generate_testcase_valid_external_deps()
    generate_testcase_single_author_deps()
    generate_testcase_monotonicity_of_deps()

def generate_testcase_relevant_dependencies():
    test_dir = Path("./testcases/relevant_dependencies")
    if os.path.exists(test_dir):
        print(f"directory {test_dir} exists already, not generating.")
        return
    
    a, b = generate_human_names(2)
    repo = Repo(str(test_dir/"db"))
    repo.create_repo()
    date = 1774010000
    a1 = add_delta_state_as_commit_plumbing(repo, [], a, date, created=100)
    b1 = add_delta_state_as_commit_plumbing(repo, [], b, date + 1, created=100)
    a2 = add_delta_state_as_commit_plumbing(repo, [a1, b1], a, date + 2, destroyed=50)

    valid_commits = [a1, b1]
    invalid_commits = [a2]

    repo.write_verification_output_expected(test_dir, list(map(lambda x: x.encode(), valid_commits)), list(map(lambda x: x.encode(), invalid_commits)))

def generate_testcase_delta_account_minimality_1():
    test_dir = Path("./testcases/delta_account_minimality_1")
    if os.path.exists(test_dir):
        print(f"directory {test_dir} exists already, not generating.")
        return
    
    a, b, c = generate_human_names(3)
    repo = Repo(str(test_dir/"db"))
    repo.create_repo()
    date = 1774010000
    a1 = add_delta_state_as_commit_plumbing(repo, [], a, date, created=100, destroyed=0)
    c1 = add_delta_state_as_commit_plumbing(repo, [], c, date + 1, created=0)
    b1 = add_delta_state_as_commit_plumbing(repo, [], b, date + 2, created=100)
    # TODO add commits to generate empty acked/given dict

    valid_commits = [b1]
    invalid_commits = [a1, c1]

    repo.write_verification_output_expected(test_dir, list(map(lambda x: x.encode(), valid_commits)), list(map(lambda x: x.encode(), invalid_commits)))

def generate_testcase_delta_account_minimality_2():
    test_dir = Path("./testcases/delta_account_minimality_2")
    if os.path.exists(test_dir):
        print(f"directory {test_dir} exists already, not generating.")
        return
    
    a, b, c, d = generate_human_names(4)
    repo = Repo(str(test_dir/"db"))
    repo.create_repo()
    date = 1774010000
    a1 = add_delta_state_as_commit_plumbing(repo, [], a, date, created=100, msg="a1")
    b1 = add_delta_state_as_commit_plumbing(repo, [], b, date + 1, created=100, msg="b1")
    c1 = add_delta_state_as_commit_plumbing(repo, [], c, date + 2, created=100, msg="c1")
    d1 = add_delta_state_as_commit_plumbing(repo, [], d, date + 3, created=100, destroyed=100, msg="d1")
    b2 = add_delta_state_as_commit_plumbing(repo, [b1, a1], b, date + 5, given={a.encode(): 10}, msg="b2")
    a2 = add_delta_state_as_commit_plumbing(repo, [a1, b2], a, date + 6, acked={b.encode(): 10}, msg="a2")
    
    b3 = add_delta_state_as_commit_plumbing(repo, [b2, a1], b, date + 7, given={a.encode(): 10}, msg="b3")
    a3 = add_delta_state_as_commit_plumbing(repo, [a2, b1], a, date + 8, acked={b.encode(): 10}, msg="a3")
    c2 = add_delta_state_as_commit_plumbing(repo, [c1], c, date + 9, created=100, msg="c2")
    d2 = add_delta_state_as_commit_plumbing(repo, [d1], d, date + 10, destroyed=100, msg="d2")

    valid_commits = [a1, b1, c1, d1, b2, a2]
    invalid_commits = [b3, a3, c2, d2]

    repo.write_verification_output_expected(test_dir, list(map(lambda x: x.encode(), valid_commits)), list(map(lambda x: x.encode(), invalid_commits)))
    
def generate_testcase_delta_account_valid_acks():
    test_dir = Path("./testcases/delta_account_valid_acks")
    if os.path.exists(test_dir):
        print(f"directory {test_dir} exists already, not generating.")
        return
    
    a, b = generate_human_names(2)
    repo = Repo(str(test_dir/"db"))
    repo.create_repo()
    date = 1774010000
    a1 = add_delta_state_as_commit_plumbing(repo, [], a, date, created=100, msg="a1")
    b1 = add_delta_state_as_commit_plumbing(repo, [], b, date + 2, created=100, msg="b1")
    b2 = add_delta_state_as_commit_plumbing(repo, [b1, a1], b, date + 3, given={a.encode(): 100}, msg="b2")
    b3 = add_delta_state_as_commit_plumbing(repo, [b2, a1], b, date + 4, acked={a.encode(): 100}, msg="b3") # `b` acks from `a` although it never got anything from `a`
    a2 = add_delta_state_as_commit_plumbing(repo, [a1, b2], a, date + 5, acked={b.encode(): 120}, msg="a2") # `a` acks too much from `b`

    valid_commits = [a1, b1, b2]
    invalid_commits = [b3, a2]

    repo.write_verification_output_expected(test_dir, list(map(lambda x: x.encode(), valid_commits)), list(map(lambda x: x.encode(), invalid_commits)))

def generate_testcase_delta_account_non_negative_balance_giving():
    test_dir = Path("./testcases/delta_account_non_negative_balance_giving")
    if os.path.exists(test_dir):
        print(f"directory {test_dir} exists already, not generating.")
        return
    
    a, b = generate_human_names(2)
    repo = Repo(str(test_dir/"db"))
    repo.create_repo()
    date = 1774010000
    a1 = add_delta_state_as_commit_plumbing(repo, [], a, date, created=100)
    b1 = add_delta_state_as_commit_plumbing(repo, [], b, date + 2, created=100)
    a2 = add_delta_state_as_commit_plumbing(repo, [a1, b1], a, date + 5, given={b.encode(): 120})

    valid_commits = [a1, b1]
    invalid_commits = [a2]

    repo.write_verification_output_expected(test_dir, list(map(lambda x: x.encode(), valid_commits)), list(map(lambda x: x.encode(), invalid_commits)))

def generate_testcase_delta_account_non_negative_balance_destroying():
    # TODO maybe add more complicated testcase to check if balance gets calculated correctly or smthn
    test_dir = Path("./testcases/delta_account_non_negative_balance_destroying")
    if os.path.exists(test_dir):
        print(f"directory {test_dir} exists already, not generating.")
        return
    
    a, b = generate_human_names(2)
    repo = Repo(str(test_dir/"db"))
    repo.create_repo()
    date = 1774010000
    a1 = add_delta_state_as_commit_plumbing(repo, [], a, date, created=100)
    b1 = add_delta_state_as_commit_plumbing(repo, [], b, date + 2, created=100)
    a2 = add_delta_state_as_commit_plumbing(repo, [a1, b1], a, date + 5, destroyed=101)

    valid_commits = [a1, b1]
    invalid_commits = [a2]

    repo.write_verification_output_expected(test_dir, list(map(lambda x: x.encode(), valid_commits)), list(map(lambda x: x.encode(), invalid_commits)))

def generate_testcase_commit_date_non_decreasing():
    test_dir = Path("./testcases/commit_date_non_decreasing")
    if os.path.exists(test_dir):
        print(f"directory {test_dir} exists already, not generating.")
        return
    
    a, = generate_human_names(1)
    repo = Repo(str(test_dir/"db"))
    repo.create_repo()
    date = 1774010000
    a1 = add_delta_state_as_commit_plumbing(repo, [], a, date, created=100)
    a2 = add_delta_state_as_commit_plumbing(repo, [a1], a, date, destroyed=100)
    a3 = add_delta_state_as_commit_plumbing(repo, [a2], a, date-1, created=101)

    valid_commits = [a1, a2]
    invalid_commits = [a3]

    repo.write_verification_output_expected(test_dir, list(map(lambda x: x.encode(), valid_commits)), list(map(lambda x: x.encode(), invalid_commits)))

def generate_testcase_misc_1():
    test_dir = Path("./testcases/misc_1")
    if os.path.exists(test_dir):
        print(f"directory {test_dir} exists already, not generating.")
        return
    
    a, b, c = generate_human_names(3)
    repo = Repo(str(test_dir/"db"))
    repo.create_repo()
    date = 1774010000
    c1 = add_delta_state_as_commit_plumbing(repo, [], c, date + 2, created=100, msg="c1")
    
    c2 = add_delta_state_as_commit_plumbing(repo, [c1], c, date + 9, created=100, msg="c2")

    valid_commits = [c1]
    invalid_commits = [c2]

    repo.write_verification_output_expected(test_dir, list(map(lambda x: x.encode(), valid_commits)), list(map(lambda x: x.encode(), invalid_commits)))

def generate_testcase_necessary_dependencies():
    test_dir = Path("./testcases/necessary_dependencies")
    if os.path.exists(test_dir):
        print(f"directory {test_dir} exists already, not generating.")
        return
    
    a, b = generate_human_names(2)
    repo = Repo(str(test_dir/"db"))
    repo.create_repo()
    date = 1774010000
    a1 = add_delta_state_as_commit_plumbing(repo, [], a, date, created=100)
    b1 = add_delta_state_as_commit_plumbing(repo, [], b, date+1, created=100)
    b2 = add_delta_state_as_commit_plumbing(repo, [b1], b, date+1, given={a.encode(): 10})

    valid_commits = [a1, b1]
    invalid_commits = [b2]

    repo.write_verification_output_expected(test_dir, list(map(lambda x: x.encode(), valid_commits)), list(map(lambda x: x.encode(), invalid_commits)))

def generate_testcase_delta_account_empty():
    test_dir = Path("./testcases/delta_account_empty")
    if os.path.exists(test_dir):
        print(f"directory {test_dir} exists already, not generating.")
        return
    
    a, b = generate_human_names(2)
    repo = Repo(str(test_dir/"db"))
    repo.create_repo()
    date = 1774010000
    a1 = add_delta_state_as_commit_plumbing(repo, [], a, date, created=100)
    b1 = add_delta_state_as_commit_plumbing(repo, [], b, date+1, created=100)
    b2 = add_delta_state_as_commit_plumbing(repo, [b1], b, date+1)

    valid_commits = [a1, b1]
    invalid_commits = [b2]

    repo.write_verification_output_expected(test_dir, list(map(lambda x: x.encode(), valid_commits)), list(map(lambda x: x.encode(), invalid_commits)))

def generate_testcase_single_author():
    test_dir = Path("./testcases/single_author")
    if os.path.exists(test_dir):
        print(f"directory {test_dir} exists already, not generating.")
        return
    
    a, b = generate_human_names(2)
    repo = Repo(str(test_dir/"db"))
    repo.create_repo()
    date = 1774010000
    a1 = add_delta_state_as_commit_plumbing(repo, [], a, date, created=100)
    b1 = add_delta_state_as_commit_plumbing(repo, [a1], b, date+1, created=100)

    valid_commits = [a1]
    invalid_commits = [b1]

    repo.write_verification_output_expected(test_dir, list(map(lambda x: x.encode(), valid_commits)), list(map(lambda x: x.encode(), invalid_commits)))

def generate_testcase_valid_external_deps():
    test_dir = Path("./testcases/valid_external_deps")
    if os.path.exists(test_dir):
        print(f"directory {test_dir} exists already, not generating.")
        return
    
    a, b = generate_human_names(2)
    repo = Repo(str(test_dir/"db"))
    repo.create_repo()
    date = 1774010000
    a1 = add_delta_state_as_commit_plumbing(repo, [], a, date, created=100)
    b1 = add_delta_state_as_commit_plumbing(repo, [], b, date+1, created=100)
    a2 = add_delta_state_as_commit_plumbing(repo, [a1, b1], a, date+1, given={b.encode(): 10}, created=0)
    b2 = add_delta_state_as_commit_plumbing(repo, [b1, a1], b, date+1, acked={a.encode(): 10})

    valid_commits = [a1, b1]
    invalid_commits = [a2, b2]

    repo.write_verification_output_expected(test_dir, list(map(lambda x: x.encode(), valid_commits)), list(map(lambda x: x.encode(), invalid_commits)))

def generate_testcase_single_author_deps():
    test_dir = Path("./testcases/single_author_deps")
    if os.path.exists(test_dir):
        print(f"directory {test_dir} exists already, not generating.")
        return
    
    a, b = generate_human_names(2)
    repo = Repo(str(test_dir/"db"))
    repo.create_repo()
    date = 1774010000
    a1 = add_delta_state_as_commit_plumbing(repo, [], a, date, created=100)
    a2 = add_delta_state_as_commit_plumbing(repo, [a1], a, date, created=100)
    b1 = add_delta_state_as_commit_plumbing(repo, [], b, date, created=100)
    b2 = add_delta_state_as_commit_plumbing(repo, [b1, a1, a2], b, date, given={a.encode(): 10})

    valid_commits = [a1, b1]
    invalid_commits = [a2, b2]

    repo.write_verification_output_expected(test_dir, list(map(lambda x: x.encode(), valid_commits)), list(map(lambda x: x.encode(), invalid_commits)))

def generate_testcase_fork_valid():
    test_dir = Path("./testcases/fork_valid")
    if os.path.exists(test_dir):
        print(f"directory {test_dir} exists already, not generating.")
        return
    
    a, b, c = generate_human_names(2)
    repo = Repo(str(test_dir/"db"))
    repo.create_repo()
    date = 1774010000
    a1 = add_delta_state_as_commit_plumbing(repo, [], a, date, created=100)
    b1 = add_delta_state_as_commit_plumbing(repo, [], b, date, created=100)
    c1 = add_delta_state_as_commit_plumbing(repo, [], c, date, created=100)
    b2 = add_delta_state_as_commit_plumbing(repo, [b1, c1], b, date, given={c.encode(): 100})
    b3 = add_delta_state_as_commit_plumbing(repo, [b1, a1], b, date, given={a.encode(): 100})
    a2 = add_delta_state_as_commit_plumbing(repo, [a1, b3], a, date, acked={b.encode(): 100})
    a3 = add_fork_proof_as_commit(repo, [b2, b3], a, b, date)

    valid_commits = [a1, b1, c1, b2, b3, a2, a3]
    invalid_commits = []

    # TODO how exactly can I store the expected output?

    repo.write_verification_output_expected(test_dir, list(map(lambda x: x.encode(), valid_commits)), list(map(lambda x: x.encode(), invalid_commits)))

def generate_testcase_fork_invalid():
    test_dir = Path("./testcases/fork_invalid")
    if os.path.exists(test_dir):
        print(f"directory {test_dir} exists already, not generating.")
        return
    
    a, b, c = generate_human_names(3)
    repo = Repo(str(test_dir/"db"))
    repo.create_repo()
    date = 1774010000
    a1 = add_delta_state_as_commit_plumbing(repo, [], a, date, created=100)
    b1 = add_delta_state_as_commit_plumbing(repo, [], b, date, created=100)
    c1 = add_delta_state_as_commit_plumbing(repo, [], c, date, created=100)
    b2 = add_delta_state_as_commit_plumbing(repo, [b1, c1], b, date, given={c.encode(): 100})
    b3 = add_delta_state_as_commit_plumbing(repo, [b1, a1], b, date, given={a.encode(): 100})
    c2 = add_delta_state_as_commit_plumbing(repo, [c1, b2], c, date, acked={b.encode(): 100})
    a2 = add_delta_state_as_commit_plumbing(repo, [a1, b3], a, date, acked={b.encode(): 100})
    a3 = add_delta_state_as_commit_plumbing(repo, [a2, c2], a, date, given={c.encode(): 100}) # since a knows about c2, it must also know about b2 and since it also knows about b3, it knows about the fork.

    valid_commits = [a1, b1, c1, b2, b3, a2]
    invalid_commits = [a3]

    # TODO how exactly can I store the expected output?

    repo.write_verification_output_expected(test_dir, list(map(lambda x: x.encode(), valid_commits)), list(map(lambda x: x.encode(), invalid_commits)))

def generate_testcase_monotonicity_of_deps():
    test_dir = Path("./testcases/monotonicity_of_deps")
    if os.path.exists(test_dir):
        print(f"directory {test_dir} exists already, not generating.")
        return
    
    a, b = generate_human_names(2)
    repo = Repo(str(test_dir/"db"))
    repo.create_repo()
    date = 1774010000
    a1 = add_delta_state_as_commit_plumbing(repo, [], a, date, created=100)
    b1 = add_delta_state_as_commit_plumbing(repo, [], b, date, created=100)
    a2 = add_delta_state_as_commit_plumbing(repo, [a1, b1], a, date, given={b.encode(): 10})
    b2 = add_delta_state_as_commit_plumbing(repo, [b1, a2], b, date, acked={a.encode(): 10})
    b3 = add_delta_state_as_commit_plumbing(repo, [b2, a1], b, date, given={a.encode(): 10})

    valid_commits = [a1, b1, a2, b2]
    invalid_commits = [b3]

    repo.write_verification_output_expected(test_dir, list(map(lambda x: x.encode(), valid_commits)), list(map(lambda x: x.encode(), invalid_commits)))


if __name__ == "__main__":
    main()