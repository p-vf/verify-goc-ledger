from pygit2 import Oid, Repository, Blob, Tree, Commit
from pygit2.enums import SortMode, ObjectType
import sys
import os
import cProfile
from typing import Tuple

from pathlib import Path
parent_folder = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(parent_folder))

from common.account import Account, Ledger, update_ledger
from common.misc import int_from_bytes

usage_str = f"usage: {sys.argv[0]} <git-directory>"

def main(git_path):
    repo = Repository(git_path +"/.git")
    head_commit = repo.lookup_reference("HEAD").resolve().target
    assert isinstance(head_commit, Oid)
    verify_repository(repo, head_commit)

def verify_repository(repo, head_commit: Oid):
    ledger = {}
    frontier = {}
    for commit in repo.walk(head_commit, SortMode.TOPOLOGICAL | SortMode.REVERSE):
        msg = verify_commit(commit, frontier)
        delta_acc, err = get_delta_acc(commit)
        # msg += verify_delta_account(delta_acc, ledger)
        update_frontier(commit, frontier)
        update_ledger(delta_acc, ledger)
        if msg: print("failed assertions while parsing commit:", msg)
        if err: print("failed assertions while parsing tree of commit:", err)

def update_frontier(commit: Commit, frontier: dict[str, Commit]):
    frontier[commit.author.name] = commit

def get_delta_acc(commit: Commit) -> Tuple[Account, list[str]]:
    a = Account(commit.author.name)
    res = []
    tree = commit.tree.peel(ObjectType.TREE)
    for child in tree:
        correct = True
        if child.name == "created":
            a.created, correct = int_from_bytes(child.peel(ObjectType.BLOB).data)
        if child.name == "destroyed":
            a.destroyed, correct = int_from_bytes(child.peel(ObjectType.BLOB).data)
        if not correct:
            res.append(f"blob {child.id} has more than the minimal amount of bytes to represent the data")
        if child.name == "acked":
            for entry in child.peel(ObjectType.TREE):
                assert entry.name is not None
                a.acked[entry.name], correct = int_from_bytes(entry.peel(ObjectType.BLOB).data)
                if not correct:
                    res.append(f"blob {child.id} has more than the minimal amount of bytes to represent the data")
        if child.name == "given":
            for entry in child.peel(ObjectType.TREE):
                assert entry.name is not None
                a.given[entry.name], correct = int_from_bytes(entry.peel(ObjectType.BLOB).data)
                if not correct:
                    res.append(f"blob {child.id} has more than the minimal amount of bytes to represent the data")
    return a, res

def verify_commit(c: Commit, frontier: dict[str, Commit]) -> list[str]:
    res = []
    name = c.author.name
    email = c.author.email
    if c.author != c.committer:
        res.append("author and committer not equal")
    email_split = email.split("@")
    if len(email_split) != 2:
        res.append(f"email has invalid format: {email}")
    else:
        email_name = email_split[0]
        email_suffix = email_split[1]
        if email_name != name:
            res.append(f"author name and prefix of email don't match: author name: {name}, email: {email}")
        if email_suffix != "gitgen.com":
            res.append(f"email doesn't have the correct suffix (expected 'gitgen.com'): {email_suffix}")
        
    # TODO verify that all the parents are valid commits (maybe we can run fsck for this?)

    parent_authors = set()
    first = True
    # print(f"commit {c.id} has following parents:")
    for p in c.parents:
        # print(f"  {p.id}")
        # verify that first parent has same author as c
        if first and p.author.name != name:
            res.append(f"first parent {p.id} of commit {c.id} does not have the same author")
        first = False
        p_name = p.author.name
        # verify that each author is in the parent commits at most once
        if p_name in parent_authors:
            res.append(f"author {p_name} appears more than once in the parents of commit {c.id}")
        parent_authors.add(p_name)
    
    # Monotonicity of commit dates of same author
    if name in frontier:
        last_time = frontier[name].commit_time
        if last_time > c.commit_time:
            res.append(f"author date is not non-decreasing: commit-time of causally older commit: {last_time}, commit-time of causally newer commit: {c.commit_time}")
    
    return res

def verify_delta_account(account: Account, ledger: Ledger) -> list[str]:
    # TODO implement this
    raise NotImplementedError()

def verify_blob_GOC(blob: Blob, last_val: int) -> bool:
    val = int.from_bytes(blob.peel(ObjectType.BLOB).data)
    if val < last_val: # should equality be permitted? (meaning the blob would be unnecessary)
        return False
    return True

if __name__ == "__main__":
    try:
        git_path = sys.argv[1]
    except:
        print(usage_str)
        exit(1)

    if not os.path.isdir(git_path):
        print(usage_str)
        exit(2)
    profile = True
    if profile:
        cProfile.run("main(git_path)", "pygit2.stats")
        print("statistics saved to ./pygit2.stats")
    else:
        main(git_path)
        
