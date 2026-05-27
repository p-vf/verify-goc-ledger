import subprocess
import sys
import os
import cProfile
import time
from typing import Tuple
import copy

from pathlib import Path

from common.git_utils import Repo, TreeDict, empty_blob
parent_folder = Path(__file__).resolve().parent
sys.path.insert(0, str(parent_folder))

from common.account import Account, Log, update_frontier, Frontier
from common.misc import PerfStatistics, bcolors, int_from_bytes

usage_str = f"usage: {sys.argv[0]} <git-directory>"

from common.datastructures import Commit, Child, Tree

# def update_ledger(commit: Commit, frontier: dict[bytes, Commit]):
#     frontier[commit.author_name] = commit

commit_format = "%H:%T:%P:%an:%ae:%at:%cn:%ce:%ct:%B"
def parse_commit(c: bytes) -> tuple[Commit | None, str | None]:
    fields = c.split(b":")
    if len(fields) != 10:
        return None, "invalid format of commit (there was a ':' too much)"
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
    return Commit(id, tree, parents, author_name, author_email, author_date, committer_name, committer_email, committer_date, body), None

def parse_tree(id, t: bytes):
    """parameter t must be the output of git ls-tree"""
    children = []
    for l in t.splitlines():
        rest, child_name = l.split(b"\t", 1)
        _, child_type, child_id = rest.split(b" ", 2)
        children.append(Child(child_id, child_type, child_name))
    return Tree(id, children)

class GitCliGocVerifier:
    def __init__(self, git_path: str, enable_perf_stats: bool):
        self.repo = Repo(git_path, commit_format=commit_format)
        self._commit_cache: dict[bytes, Commit] = {}
        self.commit_cache_hits = 0
        self._obj_cache: dict[bytes, bytes] = {}
        self.obj_cache_hits = 0
        self._account_cache: dict[bytes, tuple[Account, bool]] = {}
        self.account_cache_hits = 0
        self._valid_frontier: dict[bytes, dict[bytes, Log]] = {}
        self._forks: dict[bytes, set[bytes]] = {}

        self.perf_statistics = PerfStatistics(enable_perf_stats)

    def verify(self):
        self.perf_statistics.start()
        self._commit_cache = {}
        self._obj_cache = {}
        self._account_cache = {}
        self.account_cache_hits = 0
        self._valid_frontier = {}
        self._forks = {}

        #self._forks = self.extract_forks()

        self.perf_statistics.start_timer("retrieve_all_commits")
        commits = self.repo.retrieve_all_commits_reverse_topo_order()
        self.perf_statistics.end_timer("retrieve_all_commits")
        for c in commits:
            if len(c) == 0: # this happens at the end of the output for some reason
                continue
            commit, t = parse_commit(c)
            commit_id = c.split(b":", 1)[0]
            if commit is None:
                print(f"failed to deserialize commit {commit_id.decode()}: {t}")
                continue
            self._commit_cache[commit_id] = commit
            msg = self.verify_commit(commit)
            if msg:
                print(f"failed checks while checking commit {commit.id.decode()}, (body: {commit.body.decode().strip()}):", msg)
                continue
            self.perf_statistics.start_timer("initial_get_delta_acc")
            delta_acc, err = self.get_delta_acc(commit)
            self.perf_statistics.end_timer("initial_get_delta_acc")
            if not err:
                tmp = self.verify_delta_acc(delta_acc, commit)
                err += tmp
            if err:
                print(f"failed checks from commit {commit.id.decode()} (body: {commit.body}) as delta account: {err}")
                continue

            if commit.author_name in self._valid_frontier:
                update_frontier(delta_acc, self._valid_frontier[commit.author_name], commit)
            else:
                self._valid_frontier[commit.author_name] = {commit.author_name: Log(commit.author_name, commit, account=delta_acc)}

        self.perf_statistics.start_timer("update_valid_refs")
        for author in self._valid_frontier:
            log = self._valid_frontier[author][author]
            self.repo.update_ref(f"refs/heads/{log.author.decode()}/validated", log.last_non_forked.id.decode())
        self.perf_statistics.end_timer("update_valid_refs")
        self.perf_statistics.end()

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

    def check_if_already_verified(self, commit_ids: list[bytes]):
        frontier_commit_ids: set[Log] = set()
        for author in self._valid_frontier:
            frontier_commit_ids.add(self._valid_frontier[author][author])
        for c in commit_ids:
            if not self.repo.is_reachable(c.decode(), list(map(lambda x: x.last_non_forked.id.decode(), frontier_commit_ids))):
                return False
        return True

    def verify_commit(self, c: Commit):
        self.perf_statistics.start_timer("verify_commit")
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

        self.perf_statistics.end_timer("verify_commit")
        return res

    def verify_delta_acc(self, a: Account, commit: Commit) -> list[str]:
        """ASSUMPTION this method is only called when the commit isn't invalid yet (relevant for updating `self._valid_frontier`)"""
        # TODO we can early return as soon as we see the commit isn't valid.
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
            return ["empty delta account"]
        if len(commit.parents) == 0:
            frontier = {}
            old_acc = Account(commit.author_name)
        else:
            # === Valid external dependencies (2P-BFT-Log) ===
            self.perf_statistics.start_timer("M3")
            already_verified = self.check_if_already_verified(commit.parents)
            self.perf_statistics.end_timer("M3")
            if not already_verified:
                res.append("a parent of commit is not valid")
                return res

            frontier = self.recreate_frontier(commit.parents)
            if a.id in frontier:
                old_acc = frontier[a.id].account
            else:
                # This can only happen if the author of the parent is different from the author of this commit.
                # Will be caught in the Single author check
                old_acc = Account(commit.author_name)

            parent_iterator = iter(map(self.get_commit, commit.parents))
            first_parent = next(parent_iterator)
            self.perf_statistics.start_timer("M2;M4;M7;relevantness;necessity")
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
                if author in frontier:
                    c = frontier[author].last_non_forked.id
                    if not c in from_cs:
                        res.append(f"dependency {c} not monotonic")
            self.perf_statistics.end_timer("M2;M4;M7;relevantness;necessity")

        self.perf_statistics.start_timer("d1;d2;d3;d4")
        # === Minimality of delta account checks Part 2 ===
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
            lg = frontier.copy() # TODO avoid this copy (might be trivial, as l might not be used after this point)
            update_frontier(a, lg, commit)
            if lg[a.id].account.balance() < 0:
                if has_given:
                    res.append(f"author {a.id} didn't have enough money to give")
                if has_destroyed:
                    res.append(f"author {a.id} didn't have enough money to destroy")

        # === Valid acknowledgements check ===
        if has_acked:
            for author, amount in a.acked.items():
                if a.id not in frontier[author].account.given or frontier[author].account.given[a.id] < amount:
                    res.append(f"author {a.id} wasn't given the money they acked from {author}")
        self.perf_statistics.end_timer("d1;d2;d3;d4")
        if len(res) == 0:
            update_frontier(a, frontier, commit)
            self._valid_frontier[a.id] = frontier
        return res

    def recreate_frontier(self, commit_ids: list[bytes]) -> dict[bytes, Log]:
        assert len(commit_ids) > 0
        # TBD maybe use --first-parent to only include the relevant authors into the log!
        # Except maybe when fork detection is necessary, then we need the other authors..
        self.perf_statistics.start_timer("recreate_frontier")

        authors = set([self.get_commit(cid).author_name for cid in commit_ids])
        authors_to_consider = set.intersection(authors, self._valid_frontier)

        frontier = None
        commit_ids_set = set(commit_ids)
        for a in authors_to_consider:
            if a not in authors:
                continue
            last_commit_of_author = self._valid_frontier[a][a].last_non_forked
            if last_commit_of_author.id in commit_ids_set:
                commit_ids_set.remove(last_commit_of_author.id)
                frontier = copy.deepcopy(self._valid_frontier[a]) # TODO avoid this copy
                break

        frontier = {} if frontier is None else frontier
        from_commits = list(map(lambda x: x.decode(), commit_ids_set))
        not_from_commits = list(map(lambda x: frontier[x].last_non_forked.id.decode(), frontier))
        relevant_commit_ids = self.repo.retrieve_reachable_commits_reverse_topo_order(list(from_commits), not_from_commits)
        self.perf_statistics.end_timer("recreate_frontier")
        self.perf_statistics.start_timer("recreate_frontier_for_loop")
        for commit_id in relevant_commit_ids:
            commit = self.get_commit(commit_id)
            a, err = self.get_delta_acc(commit)
            update_frontier(a, frontier, commit)
        self.perf_statistics.end_timer("recreate_frontier_for_loop")
        return frontier

    def merge_frontier(self, frontier_a: Frontier, frontier_b: Frontier):
        """merge `frontier_a` to `frontier_b`. `frontier_a` gets modified in place"""
        for author in frontier_b:
            if author in frontier_a:
                self.merge_log(frontier_a[author], frontier_b[author])
            else:
                frontier_a[author] = frontier_b[author]

    def merge_log(self, log_a: Log, log_b: Log):
        """`log_a` and `log_b` must have the same author. `log_a` gets modified in place"""
        assert log_a.author == log_b.author
        log_a.account.merge(log_b.account)
        if log_a.fork_frontier:
            raise NotImplementedError("merge_log")
        if self.is_reachable_commit(log_a.last_non_forked, log_b.last_non_forked):
            log_a.last_non_forked = log_b.last_non_forked

    def is_reachable_commit(self, commit_a: Commit, commit_b: Commit):
        """returns true if `commit_a` is reachable from (or equal to) `commit_b`."""
        if commit_a.id == commit_b.id:
            return True
        if commit_a.id in commit_b.parents:
            return True
        return self.repo.is_reachable(commit_a.id.decode(), [commit_b.id.decode()])

    def get_commit(self, oid: bytes) -> Commit:
        if oid in self._commit_cache:
            self.commit_cache_hits += 1
            return self._commit_cache[oid]
        # TODO invalid commits should be handled here
        c, _ = parse_commit(self.repo.retrieve_single_commit(oid.decode()))
        if c is None:
            raise Exception(f"Commit {oid.decode()} invalid")
        self._commit_cache[oid] = c
        return c

    def get_delta_acc(self, commit: Commit) -> Tuple[Account, list[str]]:
        if commit.id in self._account_cache:
            a, valid = self._account_cache[commit.id]
            self.account_cache_hits += 1
            return a, [] if valid else ["invalid commit from cache"]
        a = Account(commit.author_name)
        res = []
        id = commit.tree
        tree, err = self.retrieve_and_parse_tree_v2(id)
        if err:
            return a, err
        # === Minimality of delta account checks Part 1 ===
        for child in tree:
            err = ""
            match child:
                case "c":
                    blob_data = tree[child]
                    if not isinstance(blob_data, bytes):
                        res.append("blob expected in field 'c', got something else (probably tree)")
                        continue
                    number, err = int_from_bytes(blob_data)
                    if number == 0:
                        res.append("unnecessary zero value stored in field 'c'")
                    if len(err) > 0:
                        res.append(f"field {child} of tree {id}: {err}")
                    a.created = number
                case "d":
                    blob_data = tree[child]
                    if not isinstance(blob_data, bytes):
                        res.append("blob expected in field 'd', got something else (probably tree)")
                        continue
                    number, err = int_from_bytes(blob_data)
                    if number == 0:
                        res.append("unnecessary zero value stored in field 'd'")
                    if len(err) > 0:
                        res.append(f"field {child} of tree {id}: {err}")
                    a.destroyed = number
                case "a":
                    subtree = tree[child]
                    if not isinstance(subtree, dict):
                        res.append("tree expected in field 'a', got something else (probably blob)")
                        continue
                    if not subtree:
                        res.append("unnecessary field 'a' (empty mapping)")
                    for entry in subtree:
                        blob_data = subtree[entry]
                        if not isinstance(blob_data, bytes):
                            res.append("blob expected in field 'a', got something else (probably tree)")
                            continue
                        number, err = int_from_bytes(blob_data)
                        if number == 0:
                            res.append("unnecessary zero value stored in mapping 'a'")
                        if len(err) > 0:
                            res.append(f"field {child}/{entry} of tree {id}: {err}")
                        a.acked[entry.encode()] = number
                case "g":
                    subtree = tree[child]
                    if not isinstance(subtree, dict):
                        res.append("tree expected in field 'g', got something else (probably blob)")
                        continue
                    if not subtree:
                        res.append("unnecessary field 'g' (empty mapping)")
                    for entry in subtree:
                        blob_data = subtree[entry]
                        if not isinstance(blob_data, bytes):
                            res.append("blob expected in field 'g', got something else (probably tree)")
                            continue
                        number, err = int_from_bytes(blob_data)
                        if number == 0:
                            res.append("unnecessary zero value stored in mapping 'g'")
                        if len(err) > 0:
                            res.append(f"field {child}/{entry} of tree {id}: {err}")
                        a.given[entry.encode()] = number
                case x:
                    res.append(f"there is an unnecessary field in the tree: {x}")

        self._account_cache[commit.id] = (a, len(res) == 0)
        return a, res

    def retrieve_and_parse_tree(self, tree_id: bytes, recursive: bool = False):
        t = self.repo.retrieve_tree(tree_id.decode(), recursive)
        return parse_tree(tree_id, t)

    def retrieve_and_parse_tree_v2(self, tree_id: bytes) -> tuple[TreeDict, list[str]]:
        # TODO add caching to this (_obj_cache)
        t = self.repo.retrieve_tree(tree_id.decode(), True)
        env = os.environ
        if "GIT_DIR" in env:
            del env["GIT_DIR"]
        p = None
        err = []
        res: TreeDict = {}
        for child_line in t.splitlines():
            child_attrs = child_line.split()
            assert child_attrs[1] == b"blob"

            blob_id = child_attrs[2].decode()
            if blob_id.encode() in self._obj_cache:
                blob_content = self._obj_cache[blob_id.encode()].decode()
            else:
                blob_content, err = self.repo.read_blob_fast(blob_id)
                if err is not None:
                    return {}, [f"error while reading blob {blob_id}: " + err]

            path = child_attrs[3]
            field_names = path.decode().split("/")
            assert len(field_names) > 0
            node = res
            for name in field_names[:-1]:
                assert isinstance(node, dict)
                if name in node:
                    if not isinstance(node[name], dict):
                        return {}, [f"field {name} specified multiple times"]
                    else:
                        node = node[name]
                else:
                    node[name] = {}
                    node = node[name]
            assert isinstance(node, dict)
            if field_names[-1] in node:
                return {}, [f"field {field_names[-1]} specified multiple times"]
            node[field_names[-1]] = blob_content.encode()
        if p is not None:
            p.terminate()
        return res, []

    def obj_cache_lookup(self, id: bytes) -> bytes:
        if id in self._obj_cache:
            self.obj_cache_hits += 1
            return self._obj_cache[id]
        result = self.repo.read_blob(id.decode())
        self._obj_cache[id] = result
        return result

    def generate_report_files(self, path):
        valid_refs = self.repo.retrieve_ref_commits("refs/heads/*/validated")
        frontier = self.repo.retrieve_ref_commits("refs/heads/*/last")
        if len(valid_refs) == 0:
            raise NotImplementedError("empty valid_refs not handled")
        valid = self.repo.retrieve_reachable_commits_reverse_topo_order(list(map(lambda x: x.decode(), valid_refs)))
        invalid = self.repo.retrieve_reachable_commits_reverse_topo_order(list(map(lambda x: x.decode(), frontier)), list(map(lambda x: x.decode(), valid_refs)))
        self.repo.write_verification_output(path, valid, invalid, self._forks)

def verify_repo(git_path: str, profile_file: Path | None, report_file_path: Path | None, perf_stats_file: Path | None):
    generate_stats = not perf_stats_file is None
    generate_report_files = not report_file_path is None
    g = GitCliGocVerifier(git_path, generate_stats)
    if profile_file:
        path = str(profile_file)
        cProfile.runctx("g.verify()", {}, {"g": g}, path)
        print(f"statistics saved to {path}")
    else:
        start_time = time.perf_counter_ns()
        g.verify()
        print(f"running time: {(time.perf_counter_ns() - start_time) / 1_000_000_000} s")
    print(f"cache hits:\naccount: {g.account_cache_hits}\ncommit: {g.commit_cache_hits}\nobj: {g.obj_cache_hits}")
    if generate_report_files:
        g.generate_report_files(report_file_path)
    if generate_stats:
        return g.perf_statistics.get_times()

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
    verify_repo(git_path, Path("./git-cli.stats"), Path(git_path).parent, Path(git_path).parent / "perf.csv")

if __name__ == "__main__":
    main()