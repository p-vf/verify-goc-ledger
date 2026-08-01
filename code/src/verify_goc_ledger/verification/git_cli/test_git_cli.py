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
from common.misc import CatFileParser, author_to_filename
import pprint

from pathlib import Path

from common.git_utils import Repo, TreeDict, byz_ack_msg
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
def parse_commit(c: bytes, repo: Repo) -> tuple[Commit | None, str | None]:
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

_beginsshsig = b"-----BEGIN SSH SIGNATURE-----"
_endsshsig = b"-----END SSH SIGNATURE-----"
def check_signature(m: Commit, repo: Repo):
    if m.signature_status not in [b"G", b"U"]:
        m.signature_valid = False
        return f"signature status {m.signature_status!r} does not match \"G\" or \"U\""
    else:
        cmd = ["git", "show", "--format=raw", "--no-patch", m.id.decode()]
        raw = run_cmd(cmd, cwd=repo.git_path)

        start_idx = raw.find(_beginsshsig)
        end_idx = raw.find(_endsshsig)

        if not start_idx > 0 and end_idx > 0 and end_idx > start_idx:
            return f"commit does not contain a well formed signature: {raw}"

        # "For ed25519 the 'blob' data in binary is (always) 51 bytes: a 4-byte
        # length, a 11-byte string containing (again) the algorithm name,
        # another 4-byte length, and a 32-byte value which is the actual
        # publickey value. 51 bytes is base64-encoded to 68 chars (exactly)."
        # Source: https://crypto.stackexchange.com/questions/87715/what-is-the-public-key-length-of-rsa-and-ed25519
        blob = b''.join(raw[start_idx + len(_beginsshsig):end_idx].split())
        blob_d = base64.b64decode(blob)
        pk = base64.b64encode(blob_d[14:65])
        if pk != m.author_name:
            return f"the author and the signer don't match. author: {m.author_name}, signer: {pk}"

    return ""

class Summary:
    def __init__(self, author: bytes):
        self.frontier: dict[bytes, set[bytes]] = dict()
        self.byzantine: set[bytes] = set()
        self.byz_acked: set[bytes] = set()
        self.account: Account = Account(author)
        self.recieved: dict[bytes, int] = dict()

class GitCliGocVerifier:
    def __init__(self, git_path: str, enable_perf_stats: bool, enable_summary_cache: bool):
        self.repo = Repo(git_path, commit_format=commit_format)
        self.enable_summary_cache = enable_summary_cache
        self._commit_cache: dict[bytes, Commit] = {}
        self.commit_cache_hits = 0
        self._obj_cache: dict[bytes, bytes] = {}
        self.obj_cache_hits = 0
        self._account_cache: dict[bytes, tuple[Account, bool]] = {}
        self.account_cache_hits = 0
        self.current_frontiers: dict[bytes, dict[bytes, Log]] = {}
        self.valid_commits: set[bytes] = set()
        self.invalid_commits: set[bytes] = set()
        self.valid_commit_frontier: dict[bytes, bytes] = dict()
        self.summary_cache: dict[bytes, Summary] = dict()
        self._summary_cache_hits: int = 0

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
        frontier_set: set[bytes] = set()
        for c in commits:
            if len(c) == 0: # this happens at the end of the output for some reason
                continue
            commit, err = parse_commit(c, self.repo)
            commit_id = c.split(b":", 1)[0]
            frontier_set.add(commit_id)
            if err or commit is None:
                print(f"failed to deserialize commit {commit_id.decode()}: {err}")
                continue
            frontier_set.difference_update(commit.parents)
            self._commit_cache[commit_id] = commit

            res = self.verify_message(commit)
            if not res:
                self.valid_commits.add(commit.id)
                self.valid_commit_frontier[commit.author_name] = commit.id
            else:
                print(f"commit {commit} invalid: {res}")
                self.invalid_commits.add(commit.id)

            if self.enable_summary_cache and commit.signature_valid:
                self.update_summary(commit, commit.author_name, self.summary_cache[commit.author_name])

        print(f"summary_cache hits: {self._summary_cache_hits}")
        print(f"summary_cache:\n{self.summary_cache}")
        # print(f"valid frontier: {self.valid_commit_frontier}")
        # print(f"frontier: {frontier_set}")
        for author in self.valid_commit_frontier:
            self.repo.update_ref(f"refs/heads/{author_to_filename(author.decode())}/validated", self.valid_commit_frontier[author].decode())
        # for commit_id in frontier_set:
        #     self.repo.update_ref(f"refs/heads/{commit_id.decode()}/last", commit_id.decode())
        for commit_id in self.invalid_commits:
            self.repo.update_ref(f"refs/heads/invalid/{commit_id.decode()}", commit_id.decode())
        # for commit in self.valid_commit_frontier:
        #     self.repo.update_ref(f"refs/heads/other/validated/{commit.id.decode()}", commit.id.decode())
        self.perf_statistics.end()

    def verify_message(self, m: Commit) -> list[str]:
        msg_type = self.get_msg_type(m)
        summary = self.recreate_summary(m)

        res = []

        authors: dict[bytes, set[bytes]] = dict()

        # M5
        self.perf_statistics.start_timer("signature check")
        err = check_signature(m, self.repo)
        self.perf_statistics.end_timer("signature check")
        if err:
            return [f"signature not valid: {err}"]
        m.signature_valid = True

        if len(m.parents) > 0:
            # M1
            if not self.check_if_already_verified([m.parents[0]]):
                return ["previous message of message not valid"]
            # M2
            if self.get_commit(m.parents[0]).author_name != m.author_name:
                return ["previous message of message not same author"]
            # M3
            if msg_type == MessageType.DELTA_ACC:
                if not self.check_if_already_verified(m.parents[1:]):
                    return ["immediate dependencies of account message not valid"]
            else:
                if not set(m.parents) <= set(self._commit_cache):
                    return ["there are dependencies that don't exist"]

            # M4
            for msgid in m.parents[1:]:
                author = self.get_commit(msgid).author_name
                if msg_type == MessageType.DELTA_ACC:
                    if author in authors:
                        return [f"author {author} appears more than once in dependencies"]
                    if author == m.author_name:
                        return [f"author {author} should not appear in dependencies"]
                if author not in authors:
                    authors[author] = set()
                authors[author].add(msgid)

        if len(m.parents) > 0:
            # M7, F1, F2, F3'
            for author in authors:
                if msg_type == MessageType.DELTA_ACC and author in summary.byzantine:
                    return [f"author {author} in the dependencies of account message is labelled byzantine"]
                elif msg_type == MessageType.BYZ_ACK and (author in summary.byz_acked or author not in summary.byzantine):
                    return [f"author {author} in the dependencies of byzantine acknowledgement message is already acknowledged"]
                if not authors[author] <= summary.frontier[author]:
                    return [f"dependencies {authors[author]} are not a maximal message in the frontier"]
            if msg_type == MessageType.DELTA_ACC:
                if summary.byzantine != summary.byz_acked:
                    return [f"there is unacknowledged byzantine behaviour in the causal history of account message"]

            # d8
            if self.get_commit(m.parents[0]).author_date > m.author_date:
                return [f"dates decreasing"]

        if msg_type == MessageType.DELTA_ACC:
            if m.author_name in summary.frontier:
                a_old = summary.account
            else:
                a_old = None
            a, err = self.get_delta_acc(m)
            if err:
                return err
            assert a

            # d1
            if a_old:
                assert len(m.parents) > 0
                if a.created <= a_old.created and a.created != 0:
                    return [f"delta account message: created field non-increasing"]
                if a.destroyed <= a_old.destroyed and a.destroyed != 0:
                    return [f"delta account message: destroyed field non-increasing"]
                for author in a.acked:
                    if author in a_old.acked and a.acked[author] <= a_old.acked[author]:
                        return [f"delta account message: acked field non-increasing"]
                for author in a.given:
                    if author in a_old.given and a.given[author] <= a_old.given[author]:
                        return [f"delta account message: given field non-increasing"]

            # d2
            a_new = Account(m.author_name)
            if a_old:
                a_new = copy.deepcopy(a_old)
                a_new.merge(a)
            if a_new.balance() < 0:
                return [f"balance negative"]

            # d6, d7
            relevant_authors = set(a.acked)
            for author in authors:
                if author not in relevant_authors:
                    return [f"dependencies {authors[author]} not relevant"]
                relevant_authors.remove(author)
            if relevant_authors:
                return [f"dependencies {relevant_authors} not necessary"]

            # d3
            for author in a.acked:
                if author not in summary.recieved or summary.recieved[author] < a.acked[author]:
                    return [f"author {author} did not give the amount that was acked"]

            # d4
            # not checked

            # d5
            if a_old and a.created == a.destroyed == 0 and not a.given and not a.acked:
                return ["empty non-first account message"]

        return []

    def get_msg_type(self, commit: Commit) -> MessageType:
        if commit.body == b"":
            return MessageType.BYZ_ACK
        return MessageType.DELTA_ACC

    # def update_valid_frontier(self, commit: Commit):
    #     self.valid_commit_frontier.add(commit)
    #     if len(commit.parents) == 0:
    #         self.valid_commit_frontier.add(commit)
    #     else:
    #         pc = self.get_commit(commit.parents[0])
    #         if pc in self.valid_commit_frontier:
    #             self.valid_commit_frontier.remove(pc)
    #         self.valid_commit_frontier.add(commit)

    def verify_fork_ack_commit(self, commit: Commit) -> list[str]:
        """
        Checks invariants on `commit`, assuming that `commit` represents a
        fork acknowledgement. Invariants include:
        - the parent commits are valid messages
        - the commit has at least 2 parents
        - the first parent commit is from the same author as `commit`
        - TODO the other parent commits add at least one new byzantine author to the set of previously known byzantine authors.
        - TODO the other parent commits are a minimal commits that make an author byzantine (they either belong to a fork proof or are invalid but signed)
        """
        if len(commit.parents) < 2:
            return [f"less than 2 parents"]
        if not self.get_commit(commit.parents[0]).author_name == commit.author_name:
            return [f"first parent not the same author"]
        if not self.check_if_already_verified(commit.parents):
            return [f"there are invalid parent commits"]
        return []

    def check_if_already_verified(self, commit_ids: list[bytes]):
        return self.valid_commits >= set(commit_ids)

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
        if not (has_given or has_acked or has_destroyed or has_created) and commit.parents != []:
            return ["empty delta account as non-first message"]
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
                if c.author_name not in a.acked:
                    res.append(f"dependency {c.id.decode()} not relevant")
                # === Single author dependencies check (2P-BFT-Log) ===
                if c.author_name in authors_in_deps:
                    res.append(f"author {c.author_name} appears more than once in the dependencies")
                authors_in_deps.add(c.author_name)
            # === Necessary dependencies checks ===
            for author in a.acked:
                if author not in authors_in_deps:
                    res.append(f"necessary dependency for author {author} missing (acked)")
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

    def recreate_summary(self, commit: Commit) -> Summary:
        self.perf_statistics.start_timer("summary creation")
        s = Summary(commit.author_name)
        not_commits = []
        if self.enable_summary_cache:
            if commit.author_name in self.summary_cache and len(commit.parents) > 0:
                t = self.summary_cache[commit.author_name]
                front_commits = t.frontier[commit.author_name]
                if commit.parents[0] in front_commits:
                    assert len(front_commits) == 1
                    self._summary_cache_hits += 1
                    s = t
                    not_commits = list(front_commits)

        relevant_commit_ids = self.repo.retrieve_reachable_commits_reverse_topo_order(list(map(bytes.decode, commit.parents)), list(map(bytes.decode, not_commits)))
        for commit_id in relevant_commit_ids:
            n = self.get_commit(commit_id)
            assert n.signature_valid is not None
            if not n.signature_valid:
                continue
            self.update_summary(n, commit.author_name, s)

        self.summary_cache[commit.author_name] = s

        #####################
        # authors = set([self.get_commit(cid).author_name for cid in commit_ids])
        # authors_to_consider = set.intersection(authors, self.current_frontiers)

        # frontier = None
        # commit_ids_set = set(commit_ids)
        # for a in authors_to_consider:
        #     if a not in authors:
        #         continue
        #     last_commit_of_author = self.current_frontiers[a][a].last_non_forked
        #     if last_commit_of_author.id in commit_ids_set:
        #         commit_ids_set.remove(last_commit_of_author.id)
        #         frontier = copy.deepcopy(self.current_frontiers[a]) # TODO avoid this copy
        #         break

        # frontier = {} if frontier is None else frontier
        # from_commits = list(map(lambda x: x.decode(), commit_ids_set))
        # not_from_commits = list(map(lambda x: frontier[x].last_non_forked.id.decode(), frontier))
        # relevant_commit_ids = self.repo.retrieve_reachable_commits_reverse_topo_order(list(from_commits), not_from_commits)
        # for commit_id in relevant_commit_ids:
        #     commit = self.get_commit(commit_id)
        #     a, err = self.get_delta_acc(commit)
        #     self.update_frontier(a, frontier, commit)
        self.perf_statistics.end_timer("summary creation")
        return s

    def update_summary(self, n: Commit, m_author: bytes, s: Summary):
        # if n.signature_status not in [b"U", b"G"]:
        #     continue
        if n.id in self.valid_commits:
            if self.get_msg_type(n) == MessageType.DELTA_ACC:
                a, _ = self.get_delta_acc(n)
                assert isinstance(a, Account)
                if n.author_name == m_author:
                    s.account.merge(a)
                else:
                    if m_author in a.given:
                        s.recieved[n.author_name] = max(s.recieved.get(n.author_name, 0), a.given[m_author])
            else:
                if n.author_name == m_author:
                    assert len(n.parents) > 1
                    for msgid in n.parents[1:]:
                        s.byz_acked.add(self.get_commit(msgid).author_name)
        l: set[bytes] = set()
        if n.author_name in s.frontier:
            l = s.frontier[n.author_name]
        if len(n.parents) > 0:
            l.discard(n.parents[0])
        l.add(n.id)
        if n.id not in self.valid_commits or len(l) > 1:
            s.byzantine.add(n.author_name)
        s.frontier[n.author_name] = l

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
        c, _ = parse_commit(self.repo.retrieve_single_commit(oid.decode()), self.repo)
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
        # # frontier = self.repo.retrieve_ref_commits("refs/heads/*/last")
        # if len(valid_refs) == 0:
        #     raise NotImplementedError("empty valid_refs not handled")
        # print(f"valid frontier generate_report_files: {valid_refs}")
        # print(f"frontier generate_report_files: {frontier}")
        valid_refs = self.repo.retrieve_ref_commits("refs/heads/*/validated")
        invalid = self.repo.retrieve_ref_commits("refs/heads/invalid/*")
        valid = []
        for commit_id in self.repo.retrieve_reachable_commits_reverse_topo_order(list(map(lambda x: x.decode(), valid_refs))):
            if commit_id not in invalid:
                valid.append(commit_id)
        # invalid = self.repo.retrieve_reachable_commits_reverse_topo_order(list(map(lambda x: x.decode(), frontier)), list(map(lambda x: x.decode(), valid_refs)))
        self.repo.write_verification_output(path, valid, invalid, {})

def verify_repo(git_path: str, profile_file: Path | None, report_file_path: Path | None, perf_stats_file: Path | None, enable_summary_cache: bool):
    generate_stats = not perf_stats_file is None
    generate_report_files = not report_file_path is None
    g = GitCliGocVerifier(git_path, generate_stats, enable_summary_cache)
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
    verify_repo(git_path, Path("./git-cli.stats"), Path(git_path).parent, Path(git_path).parent / "perf.csv", True)

if __name__ == "__main__":
    main()