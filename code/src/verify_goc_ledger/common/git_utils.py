import subprocess
import os
import sys

from pathlib import Path
from typing import Sequence, Iterable
parent_folder = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(parent_folder))

from common.datastructures import Commit
from common.misc import run_cmd, int_to_bytes
from common.account import Account

empty_tree = ""
empty_blob = ""
try:
    empty_tree = run_cmd("git mktree </dev/null").strip().decode() # HACK we assume we are in a repository here. Since this code is located in a repository, this will not fail as long as it is run here (from `code/`).
    empty_blob = run_cmd("git hash-object --stdin </dev/null").strip().decode() # HACK we assume we are in a repository here. Since this code is located in a repository, this will not fail as long as it is run here (from `code/`).
except:
    raise Exception("outside a git repository")

type TreeDict = dict[str, TreeDict | bytes]

class Repo:
    def __init__(self, git_path=".", keydir: Path | None = None, commit_format: str = "%H"):
        self.commit_format = commit_format
        self.keydir = keydir
        self.git_path = git_path
        self._blob_reading_proc = None

    def __del__(self):
        if self._blob_reading_proc is not None:
            self._blob_reading_proc.terminate()

    def create_commit(self, tree: str, parents: list[str], author_name: str, date: int, message: str|None =None, sign = True):
        """
        Create a commit with the given attributes. `date` is a unix timestamp.
        If `sign` is `True` and the attribute `keydir` was defined, the created
        commit is signed with the identity given by author_name, otherwise it
        isn't.
        """
        if message is None:
            message = " "
        cmd = ["git"]
        if sign and self.keydir is not None:
            cmd += ["-c", f"user.signingkey={self.keydir/author_name}.pub"]
        cmd += ["commit-tree", tree, "-m", message]
        if self.keydir is not None:
            cmd += ["-S"]

        for p in parents:
            cmd += ["-p", p]
        env = os.environ
        if date is not None:
            env["GIT_AUTHOR_DATE"] = f"{date} +0100"
            env["GIT_COMMITTER_DATE"] = f"{date} +0100"
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

    def create_tree(self, data: TreeDict, dir: str) -> str:
        return self._create_tree_internal([dir], data)[0]

    def _create_tree_internal(self, path: list[str], data: TreeDict) -> tuple[str, int]:
        added_entries = 0
        cacheinfo_opts = ""
        for n in data:
            entry = data[n]
            if isinstance(entry, bytes):
                h = self.create_blob(entry)
                added_entries += 1
                cacheinfo_opts += f" --cacheinfo 100644,{h.decode()},{str.join("/", path + [n])}"
            else:
                assert isinstance(entry, dict)
                _, new_added_entries = self._create_tree_internal(path + [n], entry)
                added_entries += new_added_entries
        if len(cacheinfo_opts) > 0:
            run_cmd(f"git update-index --add {cacheinfo_opts}", self.git_path)
        if added_entries == 0:
            res = run_cmd(f"git mktree </dev/null")
        else:
            assert len(path) > 0, "path must have positive length"
            res = run_cmd(f"git write-tree --missing-ok --prefix={str.join("/", path)}/", self.git_path)
        return bytes.strip(res).decode(), added_entries

    def reset_index(self):
        run_cmd("git rm --cached -r --ignore-unmatch .", self.git_path)

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

    def retrieve_reachable_commits_reverse_topo_order(self, from_commits: Sequence[str], not_from_commits: Sequence[str] = []):
        if len(from_commits) == 0:
            return []
        if len(not_from_commits) == 0:
            not_args = ""
        else:
            not_args = f" ^{str.join(" ^", not_from_commits)}"
        return run_cmd(f"git rev-list --reverse --topo-order {str.join(" ", from_commits)}{not_args}", cwd=self.git_path).splitlines()

    def retrieve_single_commit(self, commit_id: str):
        return run_cmd(f"git show --no-patch --format={self.commit_format} {commit_id}", cwd=self.git_path)

    def retrieve_tree(self, tree_id: str, recursive: bool = False):
        flag = ""
        if recursive:
            flag = " -r"
        return run_cmd(f"git ls-tree {tree_id}{flag}", self.git_path)

    def read_blob(self, blob_id: str):
        return run_cmd(f"git cat-file -p {blob_id}", self.git_path)

    def read_blob_fast(self, blob_id: str) -> tuple[str, str | None]:
        """
        This is a faster implementation of read_blob, with certain
        restrictions. <br>In order for the content of the blob to be
        valid, it must be encodable to utf-8 and must not contain any
        newline characters ('\\n' or '\\r'). Encoding binary information
        can be achieved using a base64 encoding or alike.

        Returns: a tuple containing the contents of the
        blob as a string and a string containing an error message if
        there was any.

        BUG: this blocks indefinitely if there are certain bytes in the
        blob, for example the byte '\\r' causes this problem."""
        # TODO implement tests (a repo that contains all possible bytes
        # in blobs) to check whether this blocks indefinitely. It seems
        # to block at `p.readlines(2)` if there is a carriage return in
        # the blob.
        if blob_id == empty_blob:
            return "", None
        env = os.environ
        if "GIT_DIR" in env:
            del env["GIT_DIR"]
        if self._blob_reading_proc is None:
            self._blob_reading_proc = subprocess.Popen("git cat-file --batch=''", shell=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE, bufsize=2, text=True, env=env, cwd=self.git_path)
        p = self._blob_reading_proc
        assert p.stdin is not None and p.stdout is not None
        p.stdin.write(blob_id + "\n")
        try:
            lines = p.stdout.readlines(2)
        except UnicodeDecodeError:
            return "", f"encoding error"
        if len(lines) != 2:
            return "", f"invalid content (may contain newline)"
        _, blob_content = lines
        blob_content = blob_content.strip()
        return blob_content, None

    def retrieve_refnames(self, refspec):
        return run_cmd(f"git for-each-ref '--format=%(refname)' {refspec}", self.git_path).splitlines()

    def retrieve_ref_commits(self, refspec):
        return run_cmd(f"git for-each-ref '--format=%(objectname)' {refspec}", self.git_path).splitlines()

    def is_reachable(self, commit: str, from_commits: Iterable[str]):
        from_commits_set = set(from_commits)
        if commit in from_commits_set:
            return True
        # here we print all the commits that are reachable from c through parent-child edges
        #   and are reachable from any commit in `from_commits` through child-parent edges
        # if there are no such commits, this means c is either in the frontier or after. however we know here that c is not in the frontier so if result is empty, we know that c happened after the frontier.
        result = run_cmd(f"git rev-list -n 1 --ancestry-path={commit} ^{commit} {str.join(" ", from_commits_set)}", cwd=self.git_path)
        return result != b""

    def run_cmd(self, cmd):
        return run_cmd(cmd, self.git_path)

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

def add_delta_account_as_commit(acc: Account, repo: Repo, msg=" ", deps: list[str]|None=None):
    """deps is a list of commit hashes that represents the commits this commit has as parents. It must not contain the last commit of the same author."""
    global date

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
    return add_delta_account_as_commit_plumbing(repo, parents, acc.id.decode(), date, msg, created, destroyed, acked, given)

ref_fmt_last = "refs/heads/%s/last"

def add_delta_account_as_commit_plumbing(repo: Repo, deps: list[str], author: str, date: int = 1774010000, msg: str = " ", created: int | None = None, destroyed: int | None = None, acked: dict[bytes, int] | None = None, given: dict[bytes, int] | None = None):
    """deps must be the full list of dependencies. If the user intends to create a valid commit, the first element of this list must be from the same author as specified in parameter `author`."""
    tree_data: TreeDict = {}
    if created is not None:
        tree_data["c"] = int_to_bytes(created)
    if destroyed is not None:
        tree_data["d"] = int_to_bytes(destroyed)

    if given is not None: # if given non-empty
        tree_given: TreeDict = {}
        for account_id, num in given.items():
            assert isinstance(account_id, bytes)
            tree_given[account_id.decode()] = int_to_bytes(num)
        tree_data["g"] = tree_given

    if acked is not None: # if acked non-empty
        tree_acked: TreeDict = {}
        for account_id, num in acked.items():
            assert isinstance(account_id, bytes)
            tree_acked[account_id.decode()] = int_to_bytes(num)
        tree_data["a"] = tree_acked

    tree_hash = repo.create_tree(tree_data, "account")
    commit_hash = repo.create_commit(tree_hash, deps, author, date, msg).decode()
    repo.reset_index()
    repo.update_ref(ref_fmt_last % author, commit_hash)
    return commit_hash

fork_proof_author_name = "FORK_PROOF"
fork_ack_msg = "FORK_ACK"
def add_fork_proof(repo: Repo, forked_commits: list[str], date: int):
    return repo.create_commit(empty_tree, forked_commits, fork_proof_author_name, date, sign=False).decode()

def add_fork_ack(repo: Repo, author: str, fork_proof_ids: list[str], date: int):
    previous = repo.show_ref(ref_fmt_last % author)
    return add_fork_ack_plumbing(repo, author, previous + fork_proof_ids, date)

def add_fork_ack_plumbing(repo: Repo, author: str, parents: list[str], date: int):
    commit_hash = repo.create_commit(empty_tree, parents, author, date, fork_ack_msg).decode()
    repo.update_ref(ref_fmt_last % author, commit_hash)
    return commit_hash