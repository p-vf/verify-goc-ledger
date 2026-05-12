import sys
import os
import cProfile
import time
from typing import Tuple

from pathlib import Path

from common.git_utils import Repo
parent_folder = Path(__file__).resolve().parent
sys.path.insert(0, str(parent_folder))

from common.account import Account, Log, update_frontier
from common.misc import int_from_bytes

usage_str = f"usage: {sys.argv[0]} <git-directory>"

from common.datastructures import Commit, Child, Tree, Statistics

# def update_ledger(commit: Commit, frontier: dict[bytes, Commit]):
#     frontier[commit.author_name] = commit

commit_format = "%H:%T:%P:%an:%ae:%at:%cn:%ce:%ct:%B"
def parse_commit(c: bytes):
    fields = c.split(b":")
    if len(fields) != 10:
        raise Exception(f"expected length 10 of commit fields. input: {c}")
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
        self.repo = Repo(git_path, commit_format=commit_format)
        self._commit_cache: dict[bytes, Commit] = {}
        self._obj_cache: dict[bytes, tuple[int, bool]] = {}
        self._account_cache: dict[bytes, tuple[Account, bool]] = {}
        self._valid_frontier: dict[bytes, dict[bytes, Log]] = {}
        self._forks: dict[bytes, set[bytes]] = {}
    
    def verify(self, generate_profile_files: bool = False):
        self._commit_cache = {}
        self._obj_cache = {}
        self._valid_frontier = {}
        self._forks = {}
    
        if generate_profile_files:
            self._performance_data = {}
    
        #self._forks = self.extract_forks()

        commits = self.repo.retrieve_all_commits_reverse_topo_order()
        for c in commits:
            if len(c) == 0: # this happens at the end of the output for some reason
                continue
            commit = parse_commit(c)
            self._commit_cache[commit.id] = commit
            msg = self.verify_commit(commit)
            delta_acc, err = self.get_delta_acc(commit)
            tmp = self.verify_delta_acc(delta_acc, commit)
            err += tmp
            
            if not (len(msg) > 0 or len(err) > 0):
                if commit.author_name in self._valid_frontier:
                    update_frontier(delta_acc, self._valid_frontier[commit.author_name], commit)
                else:
                    self._valid_frontier[commit.author_name] = {commit.author_name: Log(commit.author_name, commit)}
                self.repo.update_ref(f"refs/heads/{delta_acc.id.decode()}/validated", commit.id.decode())
            
            if msg: print(f"failed assertions while parsing commit {commit.id.decode()}:", msg)
            if err: print(f"failed assertions while checking other invariants on commit {commit.id.decode()}:", err)
        

    def extract_forks(self) -> dict[bytes, set[bytes]]:
        author_refs = self.repo.retrieve_refnames("refs/heads/*/last")
        fork_proofs = {}
        for author_ref in author_refs:
            author = bytes.removesuffix(bytes.removeprefix(author_ref, b"refs/heads/"), b"/last")
            commits_and_children = self.repo.run_git_cmd(f"rev-list --author={author.decode()} --all --children --reverse")
            # previous_children = None
            for commit_and_children in commits_and_children:
                fork_proof = set()
                _, *children = bytes.split(commit_and_children, b" ")
                for child_str in children:
                    child = self.get_commit(child_str)
                    if child.author_name == author:
                        fork_proof.add(child.id)
                
                if len(fork_proof) > 1:
                    fork_proofs[author] = set(fork_proof)
                    break

                # This would probably be a more efficient way to get ANY fork, but not necessarily the first one
                # if previous_children is None:
                #     continue
                # commit, *children = bytes.split(b"", commit_and_children)
                # if commit not in previous_children:
                #     # found fork! however, this doesn't guarantee that this is the first fork..
                #     pass
                # previous_children = children
        return fork_proofs
    
    def check_if_already_verified(self, commit_ids):
        frontier_commit_ids: set[Log] = set()
        for author in self._valid_frontier:
            frontier_commit_ids.add(self._valid_frontier[author][author])
        for c in commit_ids:
            if not self.repo.is_reachable(c.decode(), list(map(lambda x: x.last_non_forked.id.decode(), frontier_commit_ids))):
                return False
        return True
    
    def verify_commit(self, c: Commit):
        res = []
        name = c.author_name
        email = c.author_email
        if not c.author_committer_equal():
            res.append("author and committer not equal")
        email_split = email.split(b"@", 1)
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
            # TODO replace this check with a check on fork_frontier
            last_time = int(self._valid_frontier[name][name].last_non_forked.author_date)
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
        if not (has_given or has_acked or has_destroyed or has_created):
            return ["empty delta state"]
        if len(commit.parents) == 0:
            l = {}
            old_acc = Account(commit.author_name)
        else:
            l = self.recreate_ledger(commit.parents)
            if a.id in l:
                old_acc = l[a.id].account
            else:
                # This can only happen if the author of the parent is different from the author of this commit. 
                # Will be caught in the Single author check
                old_acc = Account(commit.author_name)
        if len(commit.parents) > 0:
            # === Valid external dependencies (2P-BFT-Log) ===
            if not self.check_if_already_verified(commit.parents):
                res.append("a parent of commit is not valid")
            parent_iterator = iter(map(self.get_commit, commit.parents))
            first_parent = next(parent_iterator)
            # === Single author check (2P-BFT-Log) ===
            if first_parent.author_name != a.id:
                res.append("author of first parent not the same as author")
            authors_in_deps = set()
            for c in parent_iterator:
                # === Relevantness of dependencies check ===
                if c.author_name not in a.acked \
                    and c.author_name not in a.given:
                        res.append(f"dependency {c.id.decode()} not relevant")
                # === Single author dependencies check (2P-BFT-Log) ===
                if c.author_name in authors_in_deps:
                    res.append(f"author {c.author_name} appears more than once in the dependencies")
                authors_in_deps.add(c.author_name)
            # === Necessary dependencies checks ===
            for author in a.acked:
                if author not in authors_in_deps:
                    res.append(f"necessary dependency for author {author} missing (acked)")
            for author in a.given:
                if author not in authors_in_deps:
                    res.append(f"necessary dependency for author {author} missing (given)")
            # === Monotonicity of dependencies (2P-BFT-Log) ===
            from_cs = set(commit.parents)
            for author in authors_in_deps:
                if author in l:
                    c = l[author].last_non_forked.id
                    if not c in from_cs:
                        res.append(f"dependency {c} not monotonic")

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
            lg = l.copy() # TODO avoid this copy (might be trivial, as l might not be used after this point)
            update_frontier(a, lg, commit)
            if lg[a.id].account.balance() < 0:
                if has_given:
                    res.append(f"author {a.id} didn't have enough money to give")
                if has_destroyed:
                    res.append(f"author {a.id} didn't have enough money to destroy")
        # === Valid acknowledgements check ===
        if has_acked:
            for author, amount in a.acked.items():
                if a.id not in l[author].account.given or l[author].account.given[a.id] < amount:
                    res.append(f"author {a.id} wasn't given the money they acked from {author}")
        return res
    
    def recreate_ledger(self, commit_ids: list[bytes]) -> dict[bytes, Log]:
        assert len(commit_ids) > 0
        # TBD maybe use --first-parent to only include the relevant authors into the log!
        # Except maybe when fork detection is necessary, then we need the other authors..
        ledger = {}
        relevant_commit_ids = self.repo.retrieve_reachable_commits_reverse_topo_order(list(map(lambda x: x.decode(), commit_ids)))
        for commit_id in relevant_commit_ids:
            commit = self.get_commit(commit_id)
            a, _ = self.get_delta_acc(commit)
            update_frontier(a, ledger, commit)
        return ledger

    def get_commit(self, oid: bytes) -> Commit:
        if oid in self._commit_cache:
            return self._commit_cache[oid]
        c = parse_commit(self.repo.retrieve_single_commit(oid.decode()))
        self._commit_cache[oid] = c
        return c
    
    def get_delta_acc(self, commit: Commit) -> Tuple[Account, list[str]]:
        if commit.id in self._account_cache:
            a, valid = self._account_cache[commit.id]
            return a, [] if valid else ["invalid commit from cache"]
        a = Account(commit.author_name)
        res = []
        id = commit.tree
        new_tree = self.retrieve_and_parse_tree(id)
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
                for entry in self.retrieve_and_parse_tree(child.id).children:
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
                for entry in self.retrieve_and_parse_tree(child.id).children:
                    assert entry.name is not None
                    a.given[entry.name], minimal_bytes = self.obj_cache_lookup(entry.id)
                    at_least_one_entry = True
                    if a.given[entry.name] == 0:
                        res.append("unnecessary zero value stored in mapping 'given'")
                    if not minimal_bytes:
                        res.append(f"blob {child.id.decode()} has more than the minimal amount of bytes to represent the data")
                if not at_least_one_entry:
                    res.append("unnecessary field 'given' (empty mapping)")
        self._account_cache[commit.id] = (a, len(res) == 0)
        return a, res
    
    def retrieve_and_parse_tree(self, tree_id: bytes):
        t = self.repo.retrieve_tree(tree_id.decode())
        return parse_tree(tree_id, t)
    
    def obj_cache_lookup(self, id: bytes) -> Tuple[int, bool]:
        # TODO the boolean value may be unnecessary. can be computed on the fly quite efficiently
        if id in self._obj_cache:
            return self._obj_cache[id]
        else:
            result = int_from_bytes(self.repo.read_blob(id.decode()))
            self._obj_cache[id] = result
        return result
    
    def generate_report_files(self):
        valid_refs = self.repo.retrieve_ref_commits("refs/heads/*/validated")
        frontier = self.repo.retrieve_ref_commits("refs/heads/*/last")
        if len(valid_refs) == 0:
            raise NotImplementedError("empty valid_refs not handled")
        valid = self.repo.retrieve_reachable_commits_reverse_topo_order(list(map(lambda x: x.decode(), valid_refs)))
        invalid = self.repo.retrieve_reachable_commits_reverse_topo_order(list(map(lambda x: x.decode(), frontier)), list(map(lambda x: x.decode(), valid_refs)))
        self.repo.write_verification_output(Path(self.repo.git_path).parent, valid, invalid, self._forks)

def verify_repo(git_path: str, profile_path: Path | None, generate_report_files: bool):
    g = GitCliGocVerifier(git_path)
    if profile_path:
        path = str(profile_path)
        cProfile.runctx("g.verify()", {}, {"g": g}, path)
        print(f"statistics saved to {path}")
    else:
        start_time = time.perf_counter_ns()
        g.verify()
        print(f"running time: {(time.perf_counter_ns() - start_time) / 1_000_000_000} s")
    if generate_report_files:
        g.generate_report_files()

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
    generate_report_files = True
    verify_repo(git_path, Path("./git-cli.stats"), generate_report_files)

if __name__ == "__main__":
    main()