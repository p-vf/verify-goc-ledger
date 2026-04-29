import sys
import os
import cProfile
from typing import Tuple

from pathlib import Path
parent_folder = Path(__file__).resolve().parent
sys.path.insert(0, str(parent_folder))

from common.account import Account, Ledger, update_ledger
from common.misc import int_from_bytes, run_cmd

usage_str = f"usage: {sys.argv[0]} <git-directory>"

from datastructures import Commit, Child, Tree

def update_frontier(commit: Commit, frontier: dict[bytes, Commit]):
    frontier[commit.author_name] = commit

commit_format = "%H:%T:%P:%an:%ae:%at:%cn:%ce:%ct:%B"
def parse_commit(c: bytes):
    fields = c.split(b":")
    assert len(fields) == 10
    id = fields[0]
    tree = fields[1]
    parents = fields[2].split(b" ") if len(fields[2]) > 0 else []
    author_name = fields[3]
    author_email = fields[4]
    author_date = fields[5]
    committer_name = fields[6]
    committer_email = fields[7]
    committer_date = fields[8]
    body = fields[9]
    return Commit(id, tree, parents, author_name, author_email, author_date, committer_name, committer_email, committer_date, body)

def parse_tree(id, t: bytes):
    """parameter t must be the output of git ls-tree"""
    children = []
    for l in t.splitlines():
        rest, child_name = l.split(b"\t", 1)
        _, child_type, child_id = rest.split(b" ", 2)
        children.append(Child(child_id, child_type, child_name))
    return Tree(id, children)

class GitCliGocVerifier:
    def __init__(self, git_path):
        self.git_path = git_path
        self._commit_cache = {}
        self._obj_cache = {}
        self._frontier = {}
        self._ledger = {}
    
    def verify(self):
        self._commit_cache = {}
        self._obj_cache = {}
        self._frontier = {}
        self._ledger = {}
    
        # TODO signing should also be taken into consideration
        commits = run_cmd(f"git log --all --format={commit_format} --reverse --topo-order", cwd=self.git_path)
        for c in commits.splitlines():
            if len(c) == 0: # this happens because the end of the message body always has an additional newline appended
                continue
            commit = parse_commit(c)
            self._commit_cache[commit.id] = commit
            msg = self.verify_commit(commit)
            delta_acc, err = self.get_delta_acc(commit)
            # print(delta_acc)
            # msg += verify_delta_account(delta_acc, ledger)
            update_frontier(commit, self._frontier)
            update_ledger(delta_acc, self._ledger)
            # print("====== LEDGER START ======")
            # for account in ledger.values():
            #     print(account)
            # print(" ====== LEDGER END ======")
            if msg: print("failed assertions while parsing commit:", msg)
            if err: print("failed assertions while parsing tree of commit:", err)
        
        for account in self._ledger.values():
            print(repr(account))
    
    def verify_commit(self, c):
        res = []
        name = c.author_name
        email = c.author_email
        if not c.author_committer_equal():
            res.append("author and committer not equal")
        email_split = email.split(b"@")
        if len(email_split) != 2:
            res.append(f"email has invalid format: {email}")
        else:
            email_name = email_split[0]
            email_suffix = email_split[1]
            if email_name != name:
                res.append(f"author name and prefix of email don't match: author name: {name}, email: {email}")
            if email_suffix != b"gitgen.com":
                res.append(f"email doesn't have the correct suffix (expected 'gitgen.com'): {email_suffix}")
            
        parent_authors = set()
        first = True
        # print(f"commit {c.id} has following parents:")
        for p in c.parents:
            # print(f"  {p.id}")
            # verify that first parent has same author as c
            if p in self._commit_cache:
                parent = self._commit_cache[p]
            else:
                print("cache miss!")
                str_p = run_cmd(f"git log --format={commit_format} -n 1 {p.decode()}", cwd=self.git_path)
                parent = parse_commit(str_p)
            if first and parent.author_name != name:
                res.append(f"first parent {parent.id} of commit {c.id} does not have the same author")
            first = False
            p_name = parent.author_name
            # verify that each author is in the parent commits at most once
            if p_name in parent_authors:
                res.append(f"author {p_name} appears more than once in the parents of commit {c.id}")
            parent_authors.add(p_name)
        
        # Monotonicity of commit dates of same author
        if name in self._frontier:
            last_time = int(self._frontier[name].author_date)
            if last_time > int(c.author_date):
                res.append(f"author date is not non-decreasing: commit-time of causally older commit: {last_time}, commit-time of causally newer commit: {c.author_date}")
        
        return res

    def verify_delta_acc(self, a: Account, commit: Commit):
        # if the delta account has non default values, in some fields, the following have to be checked:
        # field created: check that the author is one of the defined creators
        # field destroyed: check that the balance of the author is non-negative after this operation
        # field acked: check that the newly specified acknowledgements are reflected by a corresponding given field in the giver
        # field given: check that the balance is non-negative after this operation
        
        if a.created > 0: # we currently don't have a mechanism to check whether a person is authorised to create tokens
            pass
        raise NotImplementedError("verify_delta_acc")
    
    def recreate_ledger(self, commit_ids: list[bytes]):
        ledger = {}
        #TODO
        raise NotImplementedError("recreate_ledger")
        
    
    def get_delta_acc(self, commit: Commit) -> Tuple[Account, list[str]]:
        a = Account(commit.author_name)
        res = []
        id = commit.tree
        new_tree = parse_tree(id, run_cmd(f"git ls-tree {id.decode()}", self.git_path))
        for child in new_tree.children:
            minimal_bytes = True
            if child.name == b"created":
                a.created, minimal_bytes = self.obj_cache_lookup(child.id)
            if child.name == b"destroyed":
                a.destroyed, minimal_bytes = self.obj_cache_lookup(child.id)
            if not minimal_bytes:
                res.append(f"blob {child.id.decode()} has more than the minimal amount of bytes to represent the data")
            if child.name == b"acked":
                for entry in parse_tree(child.id, run_cmd(f"git ls-tree {child.id.decode()}", self.git_path)).children:
                    assert entry.name is not None
                    a.acked[entry.name.decode()], minimal_bytes = self.obj_cache_lookup(entry.id)
                    if not minimal_bytes:
                        res.append(f"blob {child.id.decode()} has more than the minimal amount of bytes to represent the data")
            if child.name == b"given":
                for entry in parse_tree(child.id, run_cmd(f"git ls-tree {child.id.decode()}", self.git_path)).children:
                    assert entry.name is not None
                    a.given[entry.name.decode()], minimal_bytes = self.obj_cache_lookup(entry.id)
                    if not minimal_bytes:
                        res.append(f"blob {child.id.decode()} has more than the minimal amount of bytes to represent the data")
        return a, res
    
    def obj_cache_lookup(self, id: bytes) -> Tuple[int, bool]:
        # TODO the boolean value may be unnecessary. can be computed on the fly quite efficiently
        if id in self._obj_cache:
            return self._obj_cache[id]
        else:
            result = int_from_bytes(run_cmd(f"git cat-file -p {id.decode()}", self.git_path))
            print(f"cache miss: added {result} to cache")
            self._obj_cache[id] = result
        return result

def main():
    try:
        # this is a global variable, very bad practice indeed!
        git_path = sys.argv[1]
    except:
        print(usage_str)
        exit(1)

    if not os.path.isdir(git_path):
        print(usage_str)
        print("cwd:", os.getcwd())
        exit(2)
    profile = False
    if profile:
        cProfile.run("verify_repository(self.git_path)", "git-cli.stats")
        print("statistics saved to ./git-cli.stats")
    else:
        g = GitCliGocVerifier(git_path)
        g.verify()

if __name__ == "__main__":
    main()
        