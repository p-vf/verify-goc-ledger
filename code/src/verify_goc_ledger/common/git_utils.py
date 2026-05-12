import subprocess
import os
import shutil
import sys

from pathlib import Path
from typing import Sequence
parent_folder = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(parent_folder))

from common.misc import run_cmd, validate_hash, int_to_bytes
from common.account import Account

try:
    empty_tree = run_cmd("git mktree </dev/null").strip().decode() # HACK we assume we are in a repository here. Since this code is located in a repository, this will not fail as long as it is run here (from `code/`).
except:
    raise Exception("outside a git repository")

class Repo:
    def __init__(self, git_path=".", keydir: Path | None = None, commit_format: str = "%H"):
        self.commit_format = commit_format
        self.keydir = keydir
        self.git_path = git_path

    def create_commit(self, tree: str, parents: list[str], author_name: str, message: str|None =None, date: str|None =None):
        if message is None:
            message = " "
        cmd = ["git"]
        if self.keydir is not None:
            cmd += ["-c", f"user.signingkey={self.keydir/author_name}.pub"]
        cmd += ["commit-tree", tree, "-m", message]
        if self.keydir is not None:
            cmd += ["-S"]
        
        for p in parents:
            cmd += ["-p", p]
        env = os.environ
        if date is not None:
            env["GIT_AUTHOR_DATE"] = date
            env["GIT_COMMITTER_DATE"] = date
        env["GIT_AUTHOR_NAME"] = author_name
        env["GIT_AUTHOR_EMAIL"] = author_name + "@gitgen.com"
        env["GIT_COMMITTER_NAME"] = author_name
        env["GIT_COMMITTER_EMAIL"] = author_name + "@gitgen.com"
        return run_cmd(cmd, self.git_path, env)[:-1]

    def create_blob(self, data: bytes):
        """returns hash of created object"""
        proc = subprocess.Popen("git hash-object --stdin -w", cwd=self.git_path, stdout=subprocess.PIPE, stdin=subprocess.PIPE, shell=True)
        res = bytes.strip(proc.communicate(input=data)[0])
        #print(run_cmd(f"git cat-file blob {res.decode()}", self.repo_dir))
        return res

    def create_repo(self):
        run_cmd(f"git init {self.git_path}")
        run_cmd("git config gpg.format ssh", cwd=self.git_path)

    def create_tree(self, type_hash_name: list[tuple[str, str, str]], name):
        # TODO this function is a bad interface to the user. maybe use PyGit2's Treebuilder instead
        #print(f"creating tree {type_hash_name}")
        for (t, h, n) in type_hash_name:
            if t == "tree":
                continue # maybe check that the tree object exists here
            cmd = f"git update-index --add --cacheinfo 100644 {h} {n}"
        #    print(cmd)
            run_cmd(cmd, self.git_path)
        res = bytes.strip(run_cmd(f"git write-tree --prefix={name}/", self.git_path))
        # print(f"created tree {res.decode()}")
        return res

    def reset_index(self):
        run_cmd("git rm --cached -r .", self.git_path)

    def show_ref(self, ref: str):
        res = run_cmd(f"git for-each-ref '--format=%(objectname)' {ref}", self.git_path).decode().splitlines()
        #print(f"ref {ref} resulted in {res}")
        return res

    def update_ref(self, ref: str, hash: str):
        return run_cmd(f"git update-ref {ref} {hash}", self.git_path).decode().splitlines()
    
    def retrieve_all_commits_reverse_topo_order(self):
        format_str = "--format=" + self.commit_format + " "
        commits = run_cmd(f"git log --all {format_str}--reverse -z --topo-order", cwd=self.git_path).split(b"\0")
        if len(commits) >= 1 and commits[-1] == b'':
            return commits[:-1]
        return commits
    
    def retrieve_reachable_commits(self, from_commits: Sequence[str], not_from_commits: Sequence[str] = []):
        if len(not_from_commits) == 0:
            not_args = ""
        else:
            not_args = f" ^{str.join(" ^", not_from_commits)}"
        return run_cmd(f"git rev-list {str.join(" ", from_commits)}{not_args}", cwd=self.git_path).splitlines()
    
    def retrieve_single_commit(self, commit_id: str):
        return run_cmd(f"git show --no-patch --format={self.commit_format} {commit_id}", cwd=self.git_path)
    
    def retrieve_tree(self, tree_id: str):
        return run_cmd(f"git ls-tree {tree_id}", self.git_path)
    
    def read_blob(self, blob_id: str):
        return run_cmd(f"git cat-file -p {blob_id}", self.git_path)
    
    def retrieve_refnames(self, refspec):
        return run_cmd(f"git for-each-ref '--format=%(refname)' {refspec}", self.git_path).splitlines()

    def retrieve_ref_commits(self, refspec):
        return run_cmd(f"git for-each-ref '--format=%(objectname)' {refspec}", self.git_path).splitlines()
    
    def is_reachable(self, commit: str, from_commits: list[str]):
        if commit in from_commits:
            return True
        # here we print all the commits that are reachable from c through parent-child edges 
        #   and are reachable from any commit in `from_commits` through child-parent edges
        # if there are no such commits, this means c is either in the frontier or after. however we know here that c is not in the frontier so if result is empty, we know that c happened after the frontier.
        result = run_cmd(f"git rev-list -n 1 --ancestry-path={commit} ^{commit} {str.join(" ", from_commits)}", cwd=self.git_path)
        return result != b""
    
    def run_git_cmd(self, cmd):
        return run_cmd(f"git {cmd}", self.git_path).splitlines()

    def write_verification_output(self, test_dir: Path, valid: list[bytes] | None =None, invalid: list[bytes] | None =None, forks: dict[bytes, set[bytes]] = {}, prefix: str = ""):
        if valid is not None and invalid is not None:
            for v in valid:
                if v in invalid:
                    raise Exception(f"Testcase invalid: commit {v} is in both valid and invalid list")
        if valid is not None:
            with open(test_dir/(prefix + "valid.txt"), "w+") as valid_file:
                valid_file.writelines(map(lambda x: run_cmd(f"git show {x.decode()} --no-patch", self.git_path).decode() + "\n", sorted(valid)))
        if invalid is not None:
            with open(test_dir/(prefix + "invalid.txt"), "w+") as invalid_file:
                invalid_file.writelines(map(lambda x: run_cmd(f"git show {x.decode()} --no-patch", self.git_path).decode() + "\n", sorted(invalid)))
        for author in forks:
            with open(test_dir/(prefix + author.decode() + "_fork.txt"), "w+") as fork_file:
                fork_file.writelines(map(lambda x: run_cmd(f"git show {x.decode()} --no-patch", self.git_path).decode() + "\n", sorted(forks[author])))

    def write_verification_output_expected(self, test_dir: Path, valid: list[bytes] | None =None, invalid: list[bytes] | None =None, forks: dict[bytes, set[bytes]] = {}):
        self.write_verification_output(test_dir, valid, invalid, forks, "expected_")


date = 1774010000

def add_delta_state_as_commit(acc: Account, repo: Repo, msg=" ", deps: list[str]|None=None):
    """deps is a list of commit hashes that represents the commits this commit has as parents. It must not contain the last commit of the same author."""
    # TODO make date a parameter
    global date

    tree_account = []

    created = acc.created
    destroyed = acc.destroyed
    acked = acc.acked
    given = acc.given
    if created == 0:
        created = None
    if destroyed == 0:
        destroyed = None
    if not acked:
        acked = None
    if not given:
        given = None

    ref_fmt_str = "refs/heads/%s/last"
    previous = repo.show_ref(ref_fmt_str % (acc.id.decode()))
    assert len(previous) <= 1

    if len(previous) == 0: # if this is the first commit of this author, don't add parents.
        parents = []
    elif deps is None:
        parents = repo.show_ref(ref_fmt_str % "*")
        idx = parents.index(previous[0])
        parents[0], parents[idx] = parents[idx], parents[0]
    else:
        if previous[0] in deps:
            raise Exception("previous commit in pars")
        parents = previous + deps
    date += 1
    return add_delta_state_as_commit_plumbing(repo, parents, acc.id.decode(), date, msg, created, destroyed, acked, given)

def add_delta_state_as_commit_plumbing(repo: Repo, deps: list[str], author: str, date: int = 1774010000, msg: str = " ", created: int | None = None, destroyed: int | None = None, acked: dict | None = None, given: dict | None = None):
    """deps must be the full list of dependencies. If the user intends to create a valid commit, the first element of this list must be from the same author as specified in parameter `author`."""
    tree_account = []
    if created is not None:
        created_hash = repo.create_blob(int_to_bytes(created))
        validate_hash(created_hash.decode(), "created_hash")
        tree_account.append(("blob", created_hash.decode(), "account/created"))
    if destroyed is not None:
        destroyed_hash = repo.create_blob(int_to_bytes(destroyed))
        validate_hash(destroyed_hash.decode(), "destroyed_hash")
        tree_account.append(("blob", destroyed_hash.decode(), "account/destroyed"))

    if given is not None: # if given non-empty
        tree_given = []
        for account_id, num in given.items():
            given_hash = repo.create_blob(int_to_bytes(num))
            validate_hash(given_hash.decode(), "given_hash")
            tree_given.append(("blob", given_hash.decode(), "account/given/" + account_id.decode()))
        tree_given_hash = repo.create_tree(tree_given, "account/given")
        validate_hash(tree_given_hash.decode(), "tree_given_hash")
        tree_account.append(("tree", tree_given_hash.decode(), "account/given"))

    if acked is not None: # if acked non-empty
        tree_acked = []
        for account_id, num in acked.items():
            acked_hash = repo.create_blob(int_to_bytes(num))
            validate_hash(acked_hash.decode(), "acked_hash")
            tree_acked.append(("blob", acked_hash.decode(), "account/acked/" + account_id.decode()))
        tree_acked_hash = repo.create_tree(tree_acked, "account/acked")
        validate_hash(tree_acked_hash.decode(), "tree_acked_hash")
        tree_account.append(("tree", tree_acked_hash.decode(), "acked"))

    tree_hash = repo.create_tree(tree_account, "account")
    ref_fmt_str = "refs/heads/%s/last"
    commit_hash = repo.create_commit(tree_hash.decode(), deps, author, msg, date=f"{date} +0100").decode()
    repo.reset_index()
    repo.update_ref(ref_fmt_str % author, commit_hash)
    return commit_hash

def add_fork_proof_as_commit(repo: Repo, parents: list[str], author: str, forked_author: str, date: int):
    # TODO must author and fork author be the same?
    commit_hash = repo.create_commit(empty_tree, parents, author, "FORK_PROOF", date=f"{date} +0100").decode()
    last_id = repo.retrieve_single_commit(f"refs/heads/{forked_author}/last")
    repo.update_ref(f"refs/heads/{forked_author}/forks/{last_id}", commit_hash)

    