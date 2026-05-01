import sys
import os
import cProfile
import time
from typing import Tuple

from pathlib import Path
parent_folder = Path(__file__).resolve().parent
sys.path.insert(0, str(parent_folder))

from common.account import Account, Ledger, update_ledger
from common.misc import int_from_bytes, run_cmd

usage_str = f"usage: {sys.argv[0]} <git-directory>"

from datastructures import Commit, Child, Tree, Statistics

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
    def __init__(self, git_path: str):
        self.git_path = git_path
        self._commit_cache: dict[bytes, Commit] = {}
        self._obj_cache: dict[bytes, tuple[int, bool]] = {}
        self._valid_frontier: dict[bytes, Commit] = {}
        self._ledger: dict[bytes, Account] = {}
    
    def verify(self):
        self._commit_cache = {}
        self._obj_cache = {}
        self._valid_frontier = {}
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
            tmp = self.verify_delta_acc(delta_acc, commit)
            err += tmp
            if len(err) == 0:
                if not self.check_if_already_verified(commit.parents):
                    err.append("a parent of commit is not valid")
            
            if not (msg or err):
                update_frontier(commit, self._valid_frontier)
                update_ledger(delta_acc, self._ledger)
                run_cmd(f"git update-ref refs/heads/validated/{delta_acc.id.decode()} {commit.id.decode()}", cwd=self.git_path)
            if msg: print(f"failed assertions while parsing commit {commit.id.decode()}:", msg)
            if err: print(f"failed assertions while parsing tree of commit {commit.id.decode()}:", err)
        
        for account in self._ledger.values():
            print(repr(account))
    
    def check_if_already_verified(self, commit_ids):
        frontier_commit_ids = set(map(lambda x: x.id, self._valid_frontier.values()))
        for c in commit_ids:
            if c not in frontier_commit_ids:
                # here we print all the commits that are reachable from c through parent-child edges 
                #   and are reachable from any frontier commit through child-parent edges
                # if there are no such commits, this means c is either in the frontier or after. however we know here that c is not in the frontier so if result is empty, we know that c happened after the frontier.
                result = run_cmd(f"git rev-list -n 1 --ancestry-path={c.decode()} ^{c.decode()} {bytes.join(b" ", frontier_commit_ids).decode()}", cwd=self.git_path)
                if result == b"":
                    return False
        return True
    
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
            parent = self.get_commit(p)
            if first and parent.author_name != name:
                res.append(f"first parent {parent.id} does not have the same author")
            first = False
            p_name = parent.author_name
            # verify that each author is in the parent commits at most once
            if p_name in parent_authors:
                res.append(f"author {p_name} appears more than once in the parents")
            parent_authors.add(p_name)
        
        # Monotonicity of commit dates of same author
        if name in self._valid_frontier:
            last_time = int(self._valid_frontier[name].author_date)
            if last_time > int(c.author_date):
                res.append(f"author date is not non-decreasing: commit-time of causally older commit: {last_time}, commit-time of causally newer commit: {c.author_date}")
        
        return res

    def verify_delta_acc(self, a: Account, commit: Commit) -> list[str]:
        # if the delta account has non default values, in some fields, the following have to be checked:
        # field created: check that the author is one of the defined creators
        # field destroyed: check that the balance of the author is non-negative after this operation
        # field acked: check that the newly specified acknowledgements are reflected by a corresponding given field in the giver
        # field given: check that the balance is non-negative after this operation
        
        # NOTE: here we know that if any of the fields are their respective default value 
        #       (`0` for `created` and `destroyed`, `{}` for `acked` and `given`) that 
        #       either it was stored this way in physical storage but got marked as invalid
        #       by `get_delta_acc` or it wasn't stored in the first place which means that
        #       this field cannot make the account invalid. 
        #       This is why we can skip checks on such fields.
        has_created = False
        has_destroyed = False
        has_acked = False
        has_given = False
        res = []
        if a.created > 0: # we currently don't have a mechanism to check whether a person is authorised to create tokens
            has_created = True
        if a.destroyed > 0:
            has_destroyed = True
        if a.acked:
            has_acked = True
        if a.given:
            has_given = True
        if not (has_given or has_acked or has_destroyed):
            return []
        l = self.recreate_ledger(commit.parents)
        old_acc = l[a.id]
        if len(commit.parents) > 0:
            iterator = iter(map(self.get_commit, commit.parents))
            first_parent = next(iterator)
            # === Single author check === (TODO maybe move this to a part of the code responsible for checking 2P-BFT-Log invariants)
            if first_parent.author_name != a.id:
                res.append("author of first parent not the same as author")
            # === Relevantness of dependencies checks ===
            for c in iterator:
                if c.author_name not in a.acked \
                    and c.author_name not in a.given:
                        res.append(f"dependency {c.id.decode()} not relevant")

        # === Minimality of delta state checks Part 2 ===
        if has_destroyed:
            if old_acc.destroyed >= a.destroyed:
                res.append("unnecessary field 'destroyed' (GOC not increased)")
        if has_created:
            if old_acc.created >= a.created:
                res.append("unnecessary field 'created' (GOC not increased)")
        if has_acked:
            for giver in a.acked:
                if giver in old_acc.acked:
                    if old_acc.acked[giver] >= a.acked[giver]:
                        res.append(f"unnecessary entry in mapping 'acked' (GOC not increased for giver: {giver})")
        if has_given:
            for recipient in a.given:
                if recipient in old_acc.given:
                    if old_acc.given[recipient] >= a.given[recipient]:
                        res.append(f"unnecessary entry in mapping 'given' (GOC not increased for recipient {recipient})")
        # === Non-negative balance checks ===
        if has_given or has_destroyed:
            lg = l.copy()
            update_ledger(a, lg)
            if lg[a.id].balance() < 0:
                if has_given:
                    res.append(f"author {a.id} didn't have enough money to give")
                if has_destroyed:
                    res.append(f"author {a.id} didn't have enough money to destroy")
        # === Valid acknowledgements check ===
        if has_acked:
            for author, amount in a.acked.items():
                if l[author].given[a.id] < amount:
                    res.append(f"author {a.id} wasn't given the money they acked from {author}")
        return res
    
    def recreate_ledger(self, commit_ids: list[bytes]) -> dict[bytes, Account]:
        # TODO use --first-parent to only include the relevant authors into the log!
        ledger = {}
        # TODO only allow verified commits
        relevant_commit_ids = run_cmd(f"git rev-list {bytes.join(b" ", commit_ids).decode()}", cwd=self.git_path).splitlines()
        for commit_id in relevant_commit_ids:
            commit = self.get_commit(commit_id)
            a, _ = self.get_delta_acc(commit)
            update_ledger(a, ledger)
            
        return ledger

    def get_commit(self, oid: bytes) -> Commit:
        if oid in self._commit_cache:
            return self._commit_cache[oid]
        c = parse_commit(run_cmd(f"git log --format={commit_format} -n 1 {oid.decode()}", cwd=self.git_path))
        self._commit_cache[oid] = c
        return c
    
    def get_delta_acc(self, commit: Commit) -> Tuple[Account, list[str]]:
        # TODO implement account cache
        a = Account(commit.author_name)
        res = []
        id = commit.tree
        new_tree = parse_tree(id, run_cmd(f"git ls-tree {id.decode()}", self.git_path))
        # === Minimality of delta state checks Part 1 ===
        for child in new_tree.children:
            minimal_bytes = True
            if child.name == b"created":
                a.created, minimal_bytes = self.obj_cache_lookup(child.id)
                if a.created == 0:
                    res.append("unnecessary zero value stored in field 'created'")
            if child.name == b"destroyed":
                a.destroyed, minimal_bytes = self.obj_cache_lookup(child.id)
                if a.destroyed == 0:
                    res.append("unnecessary zero value stored in field 'destroyed'")
            if not minimal_bytes:
                res.append(f"blob {child.id.decode()} has more than the minimal amount of bytes to represent the data")
            if child.name == b"acked":
                at_least_one_entry = False
                for entry in parse_tree(child.id, run_cmd(f"git ls-tree {child.id.decode()}", self.git_path)).children:
                    assert entry.name is not None
                    a.acked[entry.name], minimal_bytes = self.obj_cache_lookup(entry.id)
                    at_least_one_entry = True
                    if a.acked[entry.name] == 0:
                        res.append("unnecessary zero value stored in mapping 'acked'")
                    if not minimal_bytes:
                        res.append(f"blob {child.id.decode()} has more than the minimal amount of bytes to represent the data")
                if not at_least_one_entry:
                    res.append("unnecessary field 'acked' (empty mapping)")
            if child.name == b"given":
                at_least_one_entry = False
                for entry in parse_tree(child.id, run_cmd(f"git ls-tree {child.id.decode()}", self.git_path)).children:
                    assert entry.name is not None
                    a.given[entry.name], minimal_bytes = self.obj_cache_lookup(entry.id)
                    at_least_one_entry = True
                    if a.given[entry.name] == 0:
                        res.append("unnecessary zero value stored in mapping 'given'")
                    if not minimal_bytes:
                        res.append(f"blob {child.id.decode()} has more than the minimal amount of bytes to represent the data")
                if not at_least_one_entry:
                    res.append("unnecessary field 'given' (empty mapping)")
        return a, res
    
    def obj_cache_lookup(self, id: bytes) -> Tuple[int, bool]:
        # TODO the boolean value may be unnecessary. can be computed on the fly quite efficiently
        if id in self._obj_cache:
            return self._obj_cache[id]
        else:
            result = int_from_bytes(run_cmd(f"git cat-file -p {id.decode()}", self.git_path))
            self._obj_cache[id] = result
        return result

def main():
    # TODO add command line option to specify whether or not to profile
    # TODO add command line option to specify whether or not to 
    #      generate file of verified commits (for correctness testing) 
    #      and implement said functionality
    try:
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
        cProfile.runctx("g.verify()", {}, {"g": GitCliGocVerifier(git_path)}, "./git-cli.stats")
        print("statistics saved to ./git-cli.stats")
    else:
        g = GitCliGocVerifier(git_path)
        start_time = time.perf_counter_ns()
        g.verify()
        print(f"running time: {(time.perf_counter_ns() - start_time) / 1_000_000_000} s")

if __name__ == "__main__":
    main()
        