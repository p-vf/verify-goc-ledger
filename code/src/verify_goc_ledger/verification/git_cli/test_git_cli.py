import base64
import json
import sys
import os
import cProfile
import time
from typing import Tuple
import copy
import pushstream
from pushstream.producer import Values
from pushstream.transformer import Map, Subprocess
from pushstream.consumer import Reduce
from common.misc import CatFileParser
import pprint

from pathlib import Path

from common.git_utils import Repo, TreeDict, fork_proof_author_name, fork_ack_msg
parent_folder = Path(__file__).resolve().parent
sys.path.insert(0, str(parent_folder))

from common.account import Account, Log, MessageType, Frontier
from common.misc import PerfStatistics, get_some_entry, int_from_bytes, pformat_commit_id, run_cmd

usage_str = f"usage: {sys.argv[0]} <git-directory>"

from common.datastructures import Commit

# def update_ledger(commit: Commit, frontier: dict[bytes, Commit]):
#     frontier[commit.author_name] = commit

commit_format = "%H:%T:%P:%an:%ae:%at:%cn:%ce:%ct:%G?:%s"
num_fields = len(commit_format.split(":"))
def parse_commit(c: bytes) -> tuple[Commit | None, str | None]:
    fields = c.split(b":", num_fields - 1)
    id = fields[0]
    tree = fields[1]
    parents = fields[2].split(b" ") if len(fields[2]) > 0 else []
    author_name = fields[3]
    author_email = fields[4]
    author_date = fields[5]
    committer_name = fields[6]
    committer_email = fields[7]
    committer_date = fields[8]
    if committer_email != b"" or\
       committer_name != b"-" or\
       author_email != b"" or\
       author_date  != committer_date:
        return None, "author and committer not consistent"
    signature_status = fields[9]
    body = fields[10]
    return Commit(id, tree, parents, author_name, author_email, author_date, signature_status, body), None

class GitCliGocVerifier:
    def __init__(self, git_path: str, enable_perf_stats: bool):
        self.repo = Repo(git_path, commit_format=commit_format)
        self._commit_cache: dict[bytes, Commit] = {}
        self.commit_cache_hits = 0
        self._obj_cache: dict[bytes, bytes] = {}
        self.obj_cache_hits = 0
        self._account_cache: dict[bytes, tuple[Account, bool]] = {}
        self.account_cache_hits = 0
        self.current_frontiers: dict[bytes, dict[bytes, Log]] = {}
        self.valid_commit_frontier: set[Commit] = set()

        self.perf_statistics = PerfStatistics(enable_perf_stats)

    def verify(self):
        self.perf_statistics.start()
        self._commit_cache = {}
        self._obj_cache = {}
        self._account_cache = {}
        self.account_cache_hits = 0
        self.current_frontiers = {}

        #self._forks = self.extract_forks()

        self.perf_statistics.start_timer("commit retrieval")
        commits = self.repo.retrieve_all_commits_reverse_topo_order()
        self.perf_statistics.end_timer("commit retrieval")
        for c in commits:
            if len(c) == 0: # this happens at the end of the output for some reason
                continue
            commit, err = parse_commit(c)
            commit_id = c.split(b":", 1)[0]
            if err or commit is None:
                print(f"failed to deserialize commit {commit_id.decode()}: {err}")
                continue
            self._commit_cache[commit_id] = commit
            msg_type = self.get_msg_type(commit)
            match msg_type:
                case MessageType.BYZ_ACK:
                    err = self.verify_fork_ack_commit(commit)
                    if err:
                        print(f"failed checks on byzantine ack {commit}: {err}")
                        continue
                    acknowledged_forks = set(map(lambda p: self.get_commit(self.get_commit(p).parents[0]), commit.parents[1:]))
                    frontier = self.recreate_frontier(commit.parents)
                    for forked_commit in acknowledged_forks:
                        log = frontier[forked_commit.author_name]
                        if forked_commit == log.last_non_forked:
                            log.acked_last_non_forked = True
                    self.update_frontier(None, frontier, commit)
                    self.current_frontiers[commit.author_name] = frontier
                    self.update_valid_frontier(commit)
                case MessageType.DELTA_ACC:
                    # TODO check signature
                    delta_acc, err = self.get_delta_acc(commit)
                    if err:
                        print(f"failed checks on commit {commit} while parsing delta account: {err}")
                        continue
                    assert delta_acc is not None
                    frontier = self.recreate_frontier(commit.parents)
                    err = []
                    for log in frontier.values():
                        if not log.acked_last_non_forked:
                            err.append(f"author {commit.author_name} didn't ack forked commit {log.last_non_forked}")
                    if err:
                        print(f"failed checks on commit {commit}: {err}")
                        continue
                    err = self.verify_delta_acc(delta_acc, commit, frontier)
                    if err:
                        print(f"failed checks on commit {commit} as delta account: {err}")
                        continue
                    self.update_frontier(delta_acc, frontier, commit)
                    self.current_frontiers[delta_acc.id] = frontier
                    self.update_valid_frontier(commit)
                case x:
                    assert False, f"case {x} not handled"

        for author in self.current_frontiers:
            log = self.current_frontiers[author][author]
            commit_id = log.last_non_forked.id
            self.valid_commit_frontier.discard(self.get_commit(commit_id))
            self.repo.update_ref(f"refs/heads/{log.author.decode()}/validated", commit_id.decode())
        for commit in self.valid_commit_frontier:
            self.repo.update_ref(f"refs/heads/other/validated/{commit.id.decode()}", commit.id.decode())
        self.perf_statistics.end()

    def get_msg_type(self, commit: Commit) -> MessageType:
        if commit.body == " ":
            return MessageType.BYZ_ACK
        return MessageType.DELTA_ACC

    def update_valid_frontier(self, commit: Commit):
        self.valid_commit_frontier.add(commit)
        if len(commit.parents) == 0:
            self.valid_commit_frontier.add(commit)
        else:
            pc = self.get_commit(commit.parents[0])
            if pc in self.valid_commit_frontier:
                self.valid_commit_frontier.remove(pc)
            self.valid_commit_frontier.add(commit)

    def verify_fork_ack_commit(self, commit: Commit) -> list[str]:
        """
        Checks invariants on `commit`, assuming that `commit` represents a
        fork acknowledgement. Invariants include:
        - TODO: check the signature of the commit
        - the parent commits are valid messages
        - the commit has at least 2 parents
        - the first parent commit is from the same author as `commit`
        - the other parent commits are fork proofs
        """
        if len(commit.parents) < 2:
            return [f"less than 2 parents"]
        if not self.get_commit(commit.parents[0]).author_name == commit.author_name:
            return [f"first parent not the same author"]
        res = []
        for commit_id in commit.parents[1:]:
            curr_commit = self.get_commit(commit_id)
            if self.get_msg_type(curr_commit) != MessageType.FORK_PROOF:
                res.append(f"{pformat_commit_id(curr_commit.id)} is not a fork proof")
        if res:
            return res
        if not self.check_if_already_verified(commit.parents):
            return [f"there are invalid parent commits"]
        return []

    def check_if_already_verified(self, commit_ids: list[bytes]):
        for c in commit_ids:
            if not self.repo.is_reachable(c.decode(), map(lambda x: x.id.decode(), self.valid_commit_frontier)):
                return False
        return True

    def verify_delta_acc(self, a: Account, commit: Commit, frontier: Frontier) -> list[str]:
        """ASSUMPTION this method is only called when the commit isn't invalid yet"""
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
            assert not frontier
            old_acc = Account(commit.author_name)
        else:
            # === Valid external dependencies (2P-BFT-Log) ===
            self.perf_statistics.start_timer("M1;M3")
            already_verified = self.check_if_already_verified(commit.parents)
            self.perf_statistics.end_timer("M1;M3")
            if not already_verified:
                res.append("a parent of commit is not valid")
                return res

            if a.id in frontier:
                old_acc = frontier[a.id].account
            else:
                # This can only happen if the author of the parent is different from the author of this commit.
                # Will be caught in the Single author check
                old_acc = Account(commit.author_name)

            parent_iterator = iter(map(self.get_commit, commit.parents))
            first_parent = next(parent_iterator)
            self.perf_statistics.start_timer("M2;M4;M7;d6;d7")

            # === dates Non-decreasing ===
            if first_parent.author_date > commit.author_date:
                res.append("dates not non-decreasing")

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
            self.perf_statistics.end_timer("M2;M4;M7;d6;d7")

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
            lg = copy.deepcopy(frontier) # TODO avoid this copy (might be trivial, as frontier might not be used after this point)
            self.update_frontier(a, lg, commit)
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
        return res

    def recreate_frontier(self, commit_ids: list[bytes]) -> dict[bytes, Log]:
        if len(commit_ids) == 0: return {}
        # TBD maybe use --first-parent to only include the relevant authors into the log!
        # Except maybe when fork detection is necessary, then we need the other authors..
        self.perf_statistics.start_timer("recreate frontier")

        authors = set([self.get_commit(cid).author_name for cid in commit_ids])
        authors_to_consider = set.intersection(authors, self.current_frontiers)

        frontier = None
        commit_ids_set = set(commit_ids)
        for a in authors_to_consider:
            if a not in authors:
                continue
            last_commit_of_author = self.current_frontiers[a][a].last_non_forked
            if last_commit_of_author.id in commit_ids_set:
                commit_ids_set.remove(last_commit_of_author.id)
                frontier = copy.deepcopy(self.current_frontiers[a]) # TODO avoid this copy
                break

        frontier = {} if frontier is None else frontier
        from_commits = list(map(lambda x: x.decode(), commit_ids_set))
        not_from_commits = list(map(lambda x: frontier[x].last_non_forked.id.decode(), frontier))
        relevant_commit_ids = self.repo.retrieve_reachable_commits_reverse_topo_order(list(from_commits), not_from_commits)
        for commit_id in relevant_commit_ids:
            commit = self.get_commit(commit_id)
            a, err = self.get_delta_acc(commit)
            self.update_frontier(a, frontier, commit)
        self.perf_statistics.end_timer("recreate frontier")
        return frontier

    def update_frontier(self, account: Account | None, frontier: Frontier, last_message: Commit):
        # print(f"updating frontier {frontier} with {account}, {last_message}")
        """ASSUMPTION updates get added in reverse topological order!! (relevant for last_message)"""
        author = last_message.author_name
        if author in frontier:
            self.update_log(frontier[last_message.author_name], last_message, account)
        else:
            frontier[author] = Log(author, last_message)
            frontier[author].last_non_forked = last_message
            frontier[author].account = copy.deepcopy(account)

    def update_log(self, log_a: Log, commit: Commit, account: Account | None):
        assert (account is None) == (self.get_msg_type(commit) == MessageType.BYZ_ACK), f"expected this equality to hold.. {self.get_msg_type(commit)}"
        assert log_a.author == commit.author_name
        assert len(commit.parents) > 0, "commit has no parents"
        if not log_a.fork_proof:
            # if log_a.last_non_forked.id == commit.id:
            #     print("############# unnecessary call to update_log: ##############")
            #     print("\n".join(traceback.format_stack()))
            if log_a.last_non_forked.id == commit.parents[0]:
                log_a.last_non_forked = commit
                if account is not None:
                    log_a.account.merge(account)
            else:
                log_a.last_non_forked, log_a.fork_proof = self.find_fork_proof(set([commit, log_a.last_non_forked]), log_a.author.decode())
                log_a.acked_last_non_forked = False
                # TODO check that this is the correct way of updating the account
                if account is not None:
                    log_a.account.merge(account)
        else:
            # TODO check that this is the correct way of updating the account
            if account is not None:
                log_a.account.merge(account)
            if commit.parents[0] == get_some_entry(log_a.fork_proof).id:
                log_a.fork_proof.add(commit)
            elif self.repo.is_reachable(commit.parents[0].decode(), map(lambda x: x.id.decode(), log_a.fork_proof)):
                log_a.last_non_forked, log_a.fork_proof = self.find_fork_proof(log_a.fork_proof | set([commit]), log_a.author.decode())

    def find_fork_proof(self, from_commits: set[Commit], author: str) -> tuple[Commit, set[Commit]]:
        if len(from_commits) < 2:
            raise Exception("trying to get fork proof from less than two commits. This is likely due to update_log being called unnecessarily")
        from_commits_ids = set(map(lambda x: x.id.decode(), from_commits))
        p = self.repo.run_cmd(f"git merge-base {str.join(" ", from_commits_ids)}").decode().strip()
        if p in from_commits_ids:
            raise Exception("No fork proof found. This is likely due to update_log being called unnecessarily")
        fork_proof_line = self.repo.run_cmd(f"git rev-list --children --author={author} --all | grep {p} -m 1").decode()
        forked_commit, *fork_proof = fork_proof_line.split(" ")
        return self.get_commit(forked_commit.encode()), set(map(lambda x: self.get_commit(x.encode()), fork_proof))

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

    def get_delta_acc(self, commit: Commit) -> Tuple[Account | None, list[str]]:
        if self.get_msg_type(commit) != MessageType.DELTA_ACC: return None, []
        if commit.id in self._account_cache:
            a, valid = self._account_cache[commit.id]
            self.account_cache_hits += 1
            return a, [] if valid else ["invalid commit from cache"]
        a = Account(commit.author_name)
        res = []
        id = commit.tree
        # tree, err = self.retrieve_and_parse_tree_read_blob_content(id)
        err = []
        data = commit.body
        try:
            tree: dict = json.loads(data)
        except Exception as e:
            err.append(f"decoding failed: {e.args}, json before decoding: {data.decode()}")
            return a, err
        else:
            # tree, err = self.retrieve_tree_content(id)
            # === Minimality of delta account checks Part 1 ===
            for child in tree:
                err = ""
                match child:
                    case "c":
                        number = tree[child]
                        if not isinstance(number, int):
                            res.append("blob expected in field 'c', got something else (probably tree)")
                            continue
                        if number == 0:
                            res.append("unnecessary zero value stored in field 'c'")
                        if len(err) > 0:
                            res.append(f"field {child} of tree {id}: {err}")
                        a.created = number
                    case "d":
                        number = tree[child]
                        if not isinstance(number, int):
                            res.append("blob expected in field 'd', got something else (probably tree)")
                            continue
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
                            number = subtree[entry]
                            if not isinstance(number, int):
                                res.append("blob expected in field 'a', got something else (probably tree)")
                                continue
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
                            number = subtree[entry]
                            if not isinstance(number, int):
                                res.append("blob expected in field 'g', got something else (probably tree)")
                                continue
                            if number == 0:
                                res.append("unnecessary zero value stored in mapping 'g'")
                            if len(err) > 0:
                                res.append(f"field {child}/{entry} of tree {id}: {err}")
                            a.given[entry.encode()] = number
                    case x:
                        res.append(f"there is an unnecessary field in the tree: {x}")

        self._account_cache[commit.id] = (a, len(res) == 0)
        return a, res

    def get_delta_acc_v2(self, commit: Commit) -> Tuple[Account | None, list[str]]:
        a = Account(commit.author_name)
        raise NotImplementedError()
        return a, err

    def retrieve_and_parse_tree_read_blob_content(self, tree_id: bytes) -> tuple[TreeDict, list[str]]:
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
                self._obj_cache[blob_id.encode()] = blob_content.encode()
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

    def retrieve_tree_content(self, tree_id: bytes) -> tuple[dict[str, bytes], list[str]]:
        # TODO add caching to this (_obj_cache)
        # TODO add constraint check on the paths: only allow alphanumeric
        # characters and "/"
        t = self.repo.retrieve_tree(tree_id.decode(), True)
        env = os.environ
        if "GIT_DIR" in env:
            del env["GIT_DIR"]
        err = []
        oid_to_paths: dict[bytes, set[str]] = {}
        for child_line in t.splitlines():
            child_attrs = child_line.split(maxsplit= 3)
            assert child_attrs[1] == b"blob"

            blob_id = child_attrs[2]

            path = child_attrs[3].decode()
            if blob_id in oid_to_paths:
                oid_to_paths[blob_id].add(path)
            else:
                oid_to_paths[blob_id] = set([path])
        if err:
            return {}, err
        def reduce_to_dict(d: dict[str, bytes], x: list[tuple[bytes, bytes]]):
            for oid, content in x:
                for path in oid_to_paths[oid]:
                    d[path] = content
            return d
        res: dict[str, bytes] = {}
        def retrieve_result(_, r: dict[str, bytes]):
            nonlocal res
            res = r
        # pprint.pprint(oid_to_paths)
        pushstream.push(
            Values(map(lambda x: x + b"\n", oid_to_paths)),
            Subprocess(["git", "-C", self.repo.git_path, "cat-file", CatFileParser.batch_arg]),
            Map(CatFileParser()),
            Reduce(acc={}, reduce=reduce_to_dict, close=retrieve_result))
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
        self.repo.write_verification_output(path, valid, invalid, {})

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