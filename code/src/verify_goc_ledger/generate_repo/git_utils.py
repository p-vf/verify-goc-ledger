import subprocess
import os
import shutil
import sys

from pathlib import Path
parent_folder = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(parent_folder))

from common.misc import run_cmd, validate_hash, int_to_bytes
from common.account import Account

class Repo:
    def __init__(self, repo_dir=".", keydir: Path | None = None):
        self.keydir = keydir
        self.repo_dir = repo_dir

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
        return run_cmd(cmd, self.repo_dir, env)[:-1]

    def create_blob(self, data: bytes):
        """returns hash of created object"""
        proc = subprocess.Popen("git hash-object --stdin -w", cwd=self.repo_dir, stdout=subprocess.PIPE, stdin=subprocess.PIPE, shell=True)
        res = bytes.strip(proc.communicate(input=data)[0])
        #print(run_cmd(f"git cat-file blob {res.decode()}", self.repo_dir))
        return res

    def read_blob(self, hash: str):
        return run_cmd(f"git show {hash}", self.repo_dir)

    def create_repo(self):
        run_cmd(f"git init {self.repo_dir}")
        run_cmd("git config gpg.format ssh", cwd=self.repo_dir)

    def create_tree(self, type_hash_name: list[tuple[str, str, str]], name):
        # TODO this function is a bad interface to the user. maybe use PyGit2's Treebuilder instead
        #print(f"creating tree {type_hash_name}")
        for (t, h, n) in type_hash_name:
            if t == "tree":
                continue # maybe check that the tree object exists here
            cmd = f"git update-index --add --cacheinfo 100644 {h} {n}"
        #    print(cmd)
            run_cmd(cmd, self.repo_dir)
        res = bytes.strip(run_cmd(f"git write-tree --prefix={name}/", self.repo_dir))
        # print(f"created tree {res.decode()}")
        return res

    def reset_index(self):
        run_cmd("git rm --cached -r .", self.repo_dir)

    def show_ref(self, ref: str):
        res = run_cmd(f"git for-each-ref '--format=%(objectname)' {ref}", self.repo_dir).decode().splitlines()
        #print(f"ref {ref} resulted in {res}")
        return res

    def update_ref(self, ref: str, hash: str):
        return run_cmd(f"git update-ref {ref} {hash}", self.repo_dir).decode().splitlines()

date = 1774010000

def add_as_commit(acc: Account, repo: Repo, token_type: str="CHF", msg=" ", deps: list[str]|None=None):
    """deps is a list of commit hashes that represents the commits this commit has as parents. It must not contain the last commit of the same author."""
    # TODO make date a parameter
    global date

    tree_account = []
    if acc.created > 0:
        created_hash = repo.create_blob(int_to_bytes(acc.created))
        validate_hash(created_hash.decode(), "created_hash")
        tree_account.append(("blob", created_hash.decode(), "account/created"))
    if acc.destroyed > 0:
        destroyed_hash = repo.create_blob(int_to_bytes(acc.destroyed))
        validate_hash(destroyed_hash.decode(), "destroyed_hash")
        tree_account.append(("blob", destroyed_hash.decode(), "account/destroyed"))

    if acc.given: # if given non-empty
        tree_given = []
        for account_id, num in acc.given.items():
            given_hash = repo.create_blob(int_to_bytes(num))
            validate_hash(given_hash.decode(), "given_hash")
            tree_given.append(("blob", given_hash.decode(), "account/given/" + account_id))
        tree_given_hash = repo.create_tree(tree_given, "account/given")
        validate_hash(tree_given_hash.decode(), "tree_given_hash")
        tree_account.append(("tree", tree_given_hash.decode(), "account/given"))

    if acc.acked: # if acked non-empty
        tree_acked = []
        for account_id, num in acc.acked.items():
            acked_hash = repo.create_blob(int_to_bytes(num))
            validate_hash(acked_hash.decode(), "acked_hash")
            tree_acked.append(("blob", acked_hash.decode(), "account/acked/" + account_id))
        tree_acked_hash = repo.create_tree(tree_acked, "account/acked")
        validate_hash(tree_acked_hash.decode(), "tree_acked_hash")
        tree_account.append(("tree", tree_acked_hash.decode(), "acked"))

    tree_hash = repo.create_tree(tree_account, "account")
    ref_prefix = "refs/heads/frontier/" + token_type + "/"
    previous = repo.show_ref(ref_prefix + acc.id)
    assert len(previous) <= 1

    if len(previous) == 0: # if this is the first commit of this author, don't add parents.
        parents = []
    elif deps is None:
        parents = repo.show_ref(ref_prefix + "*")
        idx = parents.index(previous[0])
        parents[0], parents[idx] = parents[idx], parents[0]
    else:
        if previous[0] in deps:
            raise Exception("previous commit in pars")
        parents = previous + deps
    commit_hash = repo.create_commit(tree_hash.decode(), parents, acc.id, msg, date=f"{date} +0100").decode()
    repo.reset_index()
    date += 1
    repo.update_ref(ref_prefix + acc.id, commit_hash)
    return commit_hash