import random
import sys
import abc
import os
import time
import base64

from pathlib import Path
parent_folder = Path(__file__).resolve().parent
sys.path.insert(0, str(parent_folder))

from common.misc import author_to_filename, run_cmd, validate_hash, generate_human_names, ask_if_remove_dir, ParetoSampler, get_public_keys, configure_allowed_signers
from common.account import Account
from common.git_utils import Repo, add_delta_account_as_commit

class BaseRepoGenerator(abc.ABC):
    def __init__(self, repo_dir: Path, num_commits: int, num_users: int, seed: str="hello", sign: bool = True, **kwargs):
        self._repo_dir = repo_dir
        self._num_commits = num_commits
        self._num_users = num_users
        self._sign = sign
        self._seed = seed
        self.keydir = self._repo_dir/"keys"
        self.repo = Repo(str(self._repo_dir), self.keydir.absolute() if self._sign else None)
        self.authors = None
        self.kwargs = kwargs
        self.authorkeys = None

    @abc.abstractmethod
    def generate_impl(self) -> bool:
        pass

    def generate(self) -> bool:
        if self._num_commits < self._num_users:
            print("number of commits must be greater than or equal to number of users")
            return False
        if not ask_if_remove_dir(str(self._repo_dir)):
            return False

        self.repo.create_repo()
        random.seed(self._seed)

        if self._sign:
            self.authorkeys = get_public_keys(self.keydir, self._num_users)
            self.authors = self.authorkeys
            configure_allowed_signers(self._repo_dir, self.keydir, self.authors)
            print("created or read authors:")
            print("authors:", self.authorkeys, "\ncorresponding names:", self.authors)
        return self.generate_impl()

class ValidRepoGeneratorV1(BaseRepoGenerator):
    def generate_impl(self) -> bool:
        ledger: dict[bytes, Account] = dict()
        assert isinstance(self.authors, list)

        for a in self.authors:
            ledger[a.encode()] = Account(a.encode())

        num_commits = 0
        for account in ledger.values():
            act = account.create(1000)
            num_commits += 1
            add_delta_account_as_commit(act, self.repo, msg="creation of tokens")

        while num_commits < self._num_commits:
            l = list(ledger.values())
            giver = random.choice(l)
            l.remove(giver)
            acker = random.choice(l)
            amount = int(random.random() * giver.balance() * 0.2)
            if amount == 0:
                continue
            give_act = giver.give(amount, acker.id)
            ack_act = acker.ack(amount, giver.id)
            give_msg = f"{(giver.id.decode())} gave {amount} CHF to {(acker.id.decode())}, has given {giver.given[acker.id]} CHF"
            ack_msg = f"{(acker.id.decode())} acked {amount} CHF from {(giver.id.decode())}, has acked {acker.acked[giver.id]} CHF"
            num_commits += 1
            commit_give = add_delta_account_as_commit(give_act, self.repo, msg=give_msg, deps=self.repo.show_ref(f"refs/heads/{acker.id.decode()}/last"))
            validate_hash(commit_give, "commit_give")
            print(give_msg)
            if num_commits >= self._num_commits:
                break
            num_commits += 1
            commit_ack = add_delta_account_as_commit(ack_act, self.repo, msg=ack_msg, deps=self.repo.show_ref(f"refs/heads/{giver.id.decode()}/last"))
            validate_hash(commit_ack, "commit_ack")
            print(ack_msg)

        run_cmd("git update-ref HEAD $(git log --format=%H -n 1 --all)", str(self._repo_dir))

        for account in ledger.values():
            print(f"{account!r}")
        return True

class ValidRepoGeneratorPareto(BaseRepoGenerator):
    """Has an additional parameter `k: int` which determines the
    distribution of transactions per person."""
    def generate_impl(self) -> bool:
        if "k" in self.kwargs:
            k = self.kwargs["k"]
        else:
            k = 2
        assert k > 0, "parameter k must be > 0"
        assert isinstance(self.authors, list)

        ledger: dict[bytes, Account] = dict()

        for a in self.authors:
            ledger[a.encode()] = Account(a.encode())

        p = ParetoSampler(k, self.authors)

        num_commits = 0
        for account in ledger.values():
            act = account.create(1000)
            num_commits += 1
            add_delta_account_as_commit(act, self.repo, msg="creation of tokens")

        counts = {author: 0 for author in self.authors}
        for _ in range(10000):
            a, _ = p.sample_pair()
            counts[a] += 1
        print(counts)

        while num_commits < self._num_commits:
            giver_id, acker_id = p.sample_pair()
            giver = ledger[giver_id.encode()]
            acker = ledger[acker_id.encode()]
            amount = int(random.random() * giver.balance() * 0.2)
            if amount == 0:
                continue
            give_act = giver.give(amount, acker.id)
            ack_act = acker.ack(amount, giver.id)
            give_msg = f"{(giver.id.decode())} gave {amount} CHF to {(acker.id.decode())}, has given {giver.given[acker.id]} CHF"
            ack_msg = f"{(acker.id.decode())} acked {amount} CHF from {(giver.id.decode())}, has acked {acker.acked[giver.id]} CHF"
            num_commits += 1
            commit_give = add_delta_account_as_commit(give_act, self.repo, msg=give_msg, deps=self.repo.show_ref(f"refs/heads/{acker.id.decode()}/last"))
            validate_hash(commit_give, "commit_give")
            print(give_msg)
            if num_commits >= self._num_commits:
                break
            num_commits += 1
            commit_ack = add_delta_account_as_commit(ack_act, self.repo, msg=ack_msg, deps=self.repo.show_ref(f"refs/heads/{giver.id.decode()}/last"))
            validate_hash(commit_ack, "commit_ack")
            print(ack_msg)

        run_cmd("git update-ref HEAD $(git log --format=%H -n 1 --all)", str(self._repo_dir))

        for account in ledger.values():
            print(f"{account!r}")
        return True

class ValidRepoGeneratorParetoAckDelayed(BaseRepoGenerator):
    """Has an additional parameter `k: int` which determines the
    distribution of transactions per person. Additionally there is a
    parameter `ack_delay: int` which has an influence on how long the
    participants wait until they ack."""
    def generate_impl(self) -> bool:
        if "k" in self.kwargs:
            k = self.kwargs["k"]
        else:
            k = 2
        assert k > 0, "parameter k must be > 0"
        if "ack_delay" in self.kwargs:
            ack_delay = self.kwargs["ack_delay"]
        else:
            ack_delay = 10
        assert ack_delay > 0, "parameter ack_delay must be > 0"
        assert isinstance(self.authors, list)

        ledger: dict[bytes, Account] = dict()

        for a in self.authors:
            ledger[a.encode()] = Account(a.encode())

        p = ParetoSampler(k, self.authors)

        num_commits = 0
        for account in ledger.values():
            act = account.create(1000)
            num_commits += 1
            add_delta_account_as_commit(act, self.repo)
            print(f"created account {account}")
        print(ledger)

        can_ack_from: list[tuple[bytes, bytes]] = []

        while num_commits < self._num_commits:
            giver_id, acker_id = p.sample_pair()
            giver = ledger[giver_id.encode()]
            acker = ledger[acker_id.encode()]
            amount = int(random.random() * giver.balance() * 0.2)
            if amount == 0:
                continue

            if not (acker_id, giver_id) in can_ack_from:
                can_ack_from.append((acker_id.encode(), giver_id.encode()))
            give_act = giver.give(amount, acker.id)
            give_msg = f"{(giver.id.decode())} gave {amount} CHF to {(acker.id.decode())}, has given {giver.given[acker.id]} CHF"
            deps = self.repo.show_ref(f"refs/heads/{author_to_filename(acker.id.decode())}/last")
            if len(deps) == 0:
                raise Exception(f"dependencies empty: tried to query ref {f"refs/heads/{author_to_filename(acker.id.decode())}/last"}")
            commit_give = add_delta_account_as_commit(give_act, self.repo, deps=deps)
            num_commits += 1
            validate_hash(commit_give, "commit_give")
            print(give_msg)
            if num_commits >= self._num_commits:
                break
            if len(can_ack_from) < ack_delay:
                continue
            random.shuffle(can_ack_from)
            new_acker, new_giver = can_ack_from.pop()

            amount_to_ack = ledger[new_giver].given[new_acker] - (ledger[new_acker].acked[new_giver] if new_giver in ledger[new_acker].acked else 0)
            if amount_to_ack == 0:
                continue

            ack_act = ledger[new_acker].ack(amount_to_ack, new_giver)
            ack_msg = f"{(new_acker.decode())} acked {amount_to_ack} CHF from {(new_giver.decode())}"
            commit_ack = add_delta_account_as_commit(ack_act, self.repo, deps=self.repo.show_ref(f"refs/heads/{author_to_filename(new_giver.decode())}/last"))
            num_commits += 1
            validate_hash(commit_ack, "commit_ack")
            print(ack_msg)

        run_cmd("git update-ref HEAD $(git log --format=%H -n 1 --all)", str(self._repo_dir))

        for account in ledger.values():
            print(f"{account!r}")
        return True

class InvalidRepoGeneratorGoc(BaseRepoGenerator):
    def generate_impl(self):
        ledger: dict[bytes, Account] = dict()
        assert isinstance(self.authors, list)

        for a in self.authors:
            ledger[a.encode()] = Account(a.encode())

        for account in ledger.values():
            act = account.create(1000)
            add_delta_account_as_commit(act, self.repo, msg="creation of tokens")

        invalid_commit_number = self._num_commits // 2

        for i in range(self._num_commits):
            l = list(ledger.values())
            giver = random.choice(l)
            l.remove(giver)
            acker = random.choice(l)
            amount = int(random.random() * giver.balance() * 0.2)
            if i == invalid_commit_number:
                old_amount = amount
                amount = int(giver.balance() + 1)
                give_act = giver.give(amount, acker.id)
                giver.given[acker.id] = old_amount
                print(f"fraudulent participant: {giver.id.decode()}")
            else:
                give_act = giver.give(amount, acker.id)
            # By acknowledging the given amount (even when more than balance), the acker makes himself invalid as well
            ack_act = acker.ack(amount, giver.id)
            give_msg = f"{(giver.id.decode())} gave {amount} CHF to {(acker.id.decode())}, has given {giver.given[acker.id]} CHF"
            ack_msg = f"{(acker.id.decode())} acked {amount} CHF from {(giver.id.decode())}, has acked {acker.acked[giver.id]} CHF"
            commit_give = add_delta_account_as_commit(give_act, self.repo, msg=give_msg, deps=self.repo.show_ref(f"refs/heads/{acker.id.decode()}/last"))
            commit_ack = add_delta_account_as_commit(ack_act, self.repo, msg=ack_msg, deps=self.repo.show_ref(f"refs/heads/{acker.id.decode()}/last"))
            validate_hash(commit_give, "commit_give")
            validate_hash(commit_ack, "commit_ack")
            print(give_msg)
            print(ack_msg)

        run_cmd("git update-ref HEAD $(git log --format=%H -n 1 --all)", str(self._repo_dir))

        for account in ledger.values():
            print(f"{account!r}")
        return True


def main(db: Path, no_commits: int, no_users: int, seed: str, sign: bool, type: str):
    print(f"repository will be generated at {db.absolute()}")
    match type:
        case "valid_v1":
            generator = ValidRepoGeneratorV1(db, no_commits, no_users, seed, sign)
        case "invalid_goc_given":
            generator = InvalidRepoGeneratorGoc(db, no_commits, no_users, seed, sign)
        case "valid_pareto":
            generator = ValidRepoGeneratorPareto(db, no_commits, no_users, seed, sign, k=2)
        case "valid_pareto_ack_delay":
            generator = ValidRepoGeneratorParetoAckDelayed(db, no_commits, no_users, seed, sign, k=2)
        case _:
            print(f"generator type {type} invalid!")
            return False
    return generator.generate()

def generate_repo():
    import argparse
    parser = argparse.ArgumentParser(prog="generate", description="Generates a repository that contains an append-only log representing a GOC-Ledger")
    parser.add_argument("type", help="the type of transactions to generate. possible values: valid_v1, valid_pareto, invalid_goc_given, valid_pareto_ack_delay")
    parser.add_argument("-d", "--directory", help="directory of generated repository. Defaults to \"./db\"", default="./db")
    parser.add_argument("-c", "--no-commits", help="number of commits (log messages) generated. Defaults to 20", default=20)
    parser.add_argument("-u", "--no-users", help="number of users in transactions. Defaults to 4", default=4)
    parser.add_argument("-s", "--seed", help="seed used to generate random transactions. Defaults to \"hello\"", default="hello")
    parser.add_argument("--signed", help="enable/disable signing of commits. Default: --no-signed", action=argparse.BooleanOptionalAction, default=False)
    args = parser.parse_args()
    db = Path(args.directory)
    no_commits = int(args.no_commits)
    no_users = int(args.no_users)
    seed = args.seed
    sign = args.signed
    type = args.type
    if not main(db, no_commits, no_users, seed, sign, type):
        print("generation of repository not successful")
        exit(1)


if __name__ == "__main__":
    generate_repo()