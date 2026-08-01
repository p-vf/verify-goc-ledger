import base64
import json
import sys
import os
import cProfile
import time
from typing import Tuple
import copy

from pathlib import Path
parent_folder = Path(__file__).resolve().parent
sys.path.insert(0, str(parent_folder))

from common.datastructures import Summary, Account, MessageType, Commit
from common.misc import PerfStatistics, run_cmd, author_to_filename
from common.git_utils import Repo

usage_str = f"usage: {sys.argv[0]} <git-directory>"

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


def msg_type(commit: Commit) -> MessageType:
    if commit.body == b"":
        return MessageType.BYZ_ACK
    return MessageType.ACCOUNT

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

class GitCliGocLedgerVerifier:
    def __init__(self, git_path: str, enable_perf_stats: bool, enable_summary_cache: bool, check_signature: bool):
        self.repo = Repo(git_path, commit_format=commit_format)
        self.enable_summary_cache = enable_summary_cache
        self.check_signature = check_signature

        self.commit_cache: dict[bytes, Commit] = {}
        self.commit_cache_hits = 0
        self.account_cache: dict[bytes, tuple[Account, bool]] = {}
        self.account_cache_hits = 0
        self.summary_cache: dict[bytes, Summary] = dict()
        self.summary_cache_hits = 0

        self.valid_commits: set[bytes] = set()
        self.invalid_commits: set[bytes] = set()
        self.valid_commit_frontier: dict[bytes, bytes] = dict()

        self.perf_statistics = PerfStatistics(enable_perf_stats)

    def verify(self):
        self.perf_statistics.start()

        self.perf_statistics.start_timer("commit retrieval")
        commits = self.repo.retrieve_all_commits_reverse_topo_order()
        self.perf_statistics.end_timer("commit retrieval")
        frontier_set: set[bytes] = set()
        for c in commits:
            if len(c) == 0: # this happens at the end of the output for some reason
                continue
            commit, err = parse_commit(c)
            commit_id = c.split(b":", 1)[0]
            frontier_set.add(commit_id)
            if err or commit is None:
                print(f"failed to deserialize commit {commit_id.decode()}: {err}")
                continue
            frontier_set.difference_update(commit.parents)
            self.commit_cache[commit_id] = commit

            res = self.verify_message(commit)
            if not res:
                self.valid_commits.add(commit.id)
                self.valid_commit_frontier[commit.author_name] = commit.id
            else:
                print(f"commit {commit} invalid: {res}")
                self.invalid_commits.add(commit.id)

            if self.enable_summary_cache and commit.signature_valid:
                self.update_summary(commit, commit.author_name, self.summary_cache[commit.author_name])

        for author in self.valid_commit_frontier:
            self.repo.update_ref(f"refs/heads/{author_to_filename(author.decode())}/validated", self.valid_commit_frontier[author].decode())
        for commit_id in self.invalid_commits:
            self.repo.update_ref(f"refs/heads/invalid/{commit_id.decode()}", commit_id.decode())
        self.perf_statistics.end()

    def verify_message(self, m: Commit) -> list[str]:
        type = msg_type(m)
        summary = self.create_summary(m)

        authors: dict[bytes, set[bytes]] = dict()

        # M5
        if self.check_signature:
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
            if type == MessageType.ACCOUNT:
                if not self.check_if_already_verified(m.parents[1:]):
                    return ["immediate dependencies of account message not valid"]
            else:
                if not set(m.parents) <= set(self.commit_cache):
                    return ["there are dependencies that don't exist"]

            # M4
            for msgid in m.parents[1:]:
                author = self.get_commit(msgid).author_name
                if type == MessageType.ACCOUNT:
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
                if type == MessageType.ACCOUNT and author in summary.byzantine:
                    return [f"author {author} in the dependencies of account message is labelled byzantine"]
                elif type == MessageType.BYZ_ACK and (author in summary.byz_acked or author not in summary.byzantine):
                    return [f"author {author} in the dependencies of byzantine acknowledgement message is already acknowledged"]
                if not authors[author] <= summary.frontier[author]:
                    return [f"dependencies {authors[author]} are not a maximal message in the frontier"]
            if type == MessageType.ACCOUNT:
                if summary.byzantine != summary.byz_acked:
                    return [f"there is unacknowledged byzantine behaviour in the causal history of account message"]

            # d8
            if self.get_commit(m.parents[0]).author_date > m.author_date:
                return [f"dates decreasing"]

        if type == MessageType.ACCOUNT:
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

    def check_if_already_verified(self, commit_ids: list[bytes]):
        return self.valid_commits >= set(commit_ids)

    def create_summary(self, commit: Commit) -> Summary:
        self.perf_statistics.start_timer("summary creation")
        s = Summary(commit.author_name)
        not_commits = []
        if self.enable_summary_cache:
            if commit.author_name in self.summary_cache and len(commit.parents) > 0:
                t = self.summary_cache[commit.author_name]
                front_commits = t.frontier[commit.author_name]
                if commit.parents[0] in front_commits:
                    assert len(front_commits) == 1
                    self.summary_cache_hits += 1
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

        self.perf_statistics.end_timer("summary creation")
        return s

    def update_summary(self, n: Commit, m_author: bytes, s: Summary):
        if n.id in self.valid_commits:
            if msg_type(n) == MessageType.ACCOUNT:
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

    def get_commit(self, oid: bytes) -> Commit:
        if oid in self.commit_cache:
            self.commit_cache_hits += 1
            return self.commit_cache[oid]
        c, _ = parse_commit(self.repo.retrieve_single_commit(oid.decode()))
        if c is None:
            raise Exception(f"Commit {oid.decode()} invalid")
        self.commit_cache[oid] = c
        return c

    def get_delta_acc(self, commit: Commit) -> Tuple[Account | None, list[str]]:
        if msg_type(commit) != MessageType.ACCOUNT: return None, []
        if commit.id in self.account_cache:
            a, valid = self.account_cache[commit.id]
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

        self.account_cache[commit.id] = (a, len(res) == 0)
        return a, res

    def generate_report_files(self, path):
        valid_refs = self.repo.retrieve_ref_commits("refs/heads/*/validated")
        invalid = self.repo.retrieve_ref_commits("refs/heads/invalid/*")
        valid = []
        for commit_id in self.repo.retrieve_reachable_commits_reverse_topo_order(list(map(lambda x: x.decode(), valid_refs))):
            if commit_id not in invalid:
                valid.append(commit_id)
        # invalid = self.repo.retrieve_reachable_commits_reverse_topo_order(list(map(lambda x: x.decode(), frontier)), list(map(lambda x: x.decode(), valid_refs)))
        self.repo.write_verification_output(path, valid, invalid, {})

def verify_repo(git_path: str, profile_file: Path | None, report_file_path: Path | None, perf_stats_file: Path | None, enable_summary_cache: bool, check_signature: bool):
    generate_stats = not perf_stats_file is None
    generate_report_files = not report_file_path is None
    g = GitCliGocLedgerVerifier(git_path, generate_stats, enable_summary_cache, check_signature)
    if profile_file:
        path = str(profile_file)
        cProfile.runctx("g.verify()", {}, {"g": g}, path)
        print(f"statistics saved to {path}")
    else:
        start_time = time.perf_counter_ns()
        g.verify()
        print(f"running time: {(time.perf_counter_ns() - start_time) / 1_000_000_000} s")
    print(f"cache hits:\naccount: {g.account_cache_hits}\ncommit: {g.commit_cache_hits}\nsummary: {g.summary_cache_hits}")
    if generate_report_files:
        g.generate_report_files(report_file_path)
    if generate_stats:
        return g.perf_statistics.get_times()

def main():
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
    verify_repo(git_path, Path("./git-cli.stats"), Path(git_path).parent, Path(git_path).parent / "perf.csv", True, True)

if __name__ == "__main__":
    main()