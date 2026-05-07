import random
import sys
import os
import shutil

from pathlib import Path
parent_folder = Path(__file__).resolve().parent
sys.path.insert(0, str(parent_folder))

from common.misc import run_cmd, validate_hash, generate_human_names
from common.account import Account
from common.git_utils import Repo, add_delta_state_as_commit

class ValidRepoGeneratorV1:
    def __init__(self, repo_dir: Path, num_commits: int, num_users: int, seed: str="hello", sign: bool = True):
        self._repo_dir = repo_dir
        self._num_commits = num_commits
        self._num_users = num_users
        self._sign = sign
        self._seed = seed
        pass

    def generate(self):
        if os.path.exists(self._repo_dir):
            conf = input(f"the directory {self._repo_dir} exists already. Replace it? [Y/n] ")
            if conf.lower() == "y":
                print(f"deleting directory {self._repo_dir}")
                shutil.rmtree(self._repo_dir)
            else:
                print("aborting")
                exit(1)
        
        keydir = self._repo_dir/"keys"
        repo = Repo(str(self._repo_dir), keydir.absolute() if self._sign else None)
        repo.create_repo()
        random.seed(self._seed)

        authors = generate_human_names(self._num_users)

        if self._sign:
            authorkeys = get_public_keys(keydir, authors)
            configure_allowed_signers(self._repo_dir, keydir, authors)
            print("created or read authors:")
            print("authors:", authorkeys, "\ncorresponding names:", authors)

        ledger: dict[bytes, Account] = dict()

        for a in authors:
            ledger[a.encode()] = Account(a.encode())

        for account in ledger.values():
            act = account.create(1000)
            add_delta_state_as_commit(act, repo, msg="creation of tokens")

        for i in range(self._num_commits):
            l = list(ledger.values())
            giver = random.choice(l)
            l.remove(giver)
            acker = random.choice(l)
            amount = int(random.random() * giver.balance() * 0.2)
            give_act = giver.give(amount, acker.id)
            ack_act = acker.ack(amount, giver.id)
            give_msg = f"{(giver.id.decode())} gave {amount} CHF to {(acker.id.decode())}, has given {giver.given[acker.id]} CHF"
            ack_msg = f"{(acker.id.decode())} acked {amount} CHF from {(giver.id.decode())}, has acked {acker.acked[giver.id]} CHF"
            commit_give = add_delta_state_as_commit(give_act, repo, msg=give_msg, deps=repo.show_ref("refs/heads/frontier/CHF/" + acker.id.decode()))
            commit_ack = add_delta_state_as_commit(ack_act, repo, msg=ack_msg, deps=repo.show_ref("refs/heads/frontier/CHF/" + giver.id.decode()))
            validate_hash(commit_give, "commit_give")
            validate_hash(commit_ack, "commit_ack")
            print(give_msg)
            print(ack_msg)

        run_cmd("git update-ref HEAD $(git log --format=%H -n 1 --all)", str(self._repo_dir))

        for account in ledger.values():
            print(f"{account!r}")

# TODO for v2: generate transactions where the number of transactions per person follows a pareto distribution

class InvalidRepoGeneratorGoc:
    def __init__(self, repo_dir: Path, num_commits: int, num_users: int, seed: str="hello", sign: bool = True):
        self._repo_dir = repo_dir
        self._num_commits = num_commits
        self._num_users = num_users
        self._sign = sign
        self._seed = seed
        pass

    def generate(self):
        if os.path.exists(self._repo_dir):
            conf = input(f"the directory {self._repo_dir} exists already. Replace it? [Y/n] ")
            if conf.lower() == "y":
                print(f"deleting directory {self._repo_dir}")
                shutil.rmtree(self._repo_dir)
            else:
                print("aborting")
                exit(1)
        
        keydir = self._repo_dir/"keys"
        repo = Repo(str(self._repo_dir), keydir.absolute() if self._sign else None)
        repo.create_repo()
        random.seed(self._seed)

        authors = generate_human_names(self._num_users)

        if self._sign:
            authorkeys = get_public_keys(keydir, authors)
            configure_allowed_signers(self._repo_dir, keydir, authors)
            print("created or read authors:")
            print("authors:", authorkeys, "\ncorresponding names:", authors)

        ledger: dict[bytes, Account] = dict()

        for a in authors:
            ledger[a.encode()] = Account(a.encode())

        for account in ledger.values():
            act = account.create(1000)
            add_delta_state_as_commit(act, repo, msg="creation of tokens")
        
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
            commit_give = add_delta_state_as_commit(give_act, repo, msg=give_msg, deps=repo.show_ref("refs/heads/frontier/CHF/" + acker.id.decode()))
            commit_ack = add_delta_state_as_commit(ack_act, repo, msg=ack_msg, deps=repo.show_ref("refs/heads/frontier/CHF/" + giver.id.decode()))
            validate_hash(commit_give, "commit_give")
            validate_hash(commit_ack, "commit_ack")
            print(give_msg)
            print(ack_msg)

        run_cmd("git update-ref HEAD $(git log --format=%H -n 1 --all)", str(self._repo_dir))

        for account in ledger.values():
            print(f"{account!r}")
    

def get_public_keys(keydir: Path, names):
    ids: list[str] = []
    run_cmd(f"mkdir -p {keydir}") # in case the key directory doesn't exist
    print(run_cmd(f"pwd"))
    for n in names:
        run_cmd(f"ssh-keygen -f {keydir/n} -N \"\" -q -t ed25519 -C \"\"") # if the keys don't exist, create them
        ids.append(run_cmd(f"ssh-keygen -f {keydir/n} -e | head -n 3 | tail -n 1").decode().strip())
    return ids

def configure_allowed_signers(repo_dir: Path, keydir: Path, author_names: list[str]):
    allowed_signers_path = "allowed_signers.txt"
    with open(repo_dir/allowed_signers_path, "w") as file:
        lines = []
        for a in author_names:
            lines.append(a + "@gitgen.com namespace=\"git\" " + run_cmd(f"cat {keydir/a}.pub").decode().strip() + "\r\n")
        file.writelines(lines)
    
    run_cmd(f"git config gpg.ssh.allowedSignersFile {allowed_signers_path}", cwd=str(repo_dir))

import argparse
def generate_repo():
    parser = argparse.ArgumentParser(prog="generate", description="Generates a repository that contains an append-only log representing a GOC-Ledger")
    parser.add_argument("type", help="the type of transactions to generate. possible values: valid_v1, invalid_goc_given")
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
    match type:
        case "valid_v1":
            generator = ValidRepoGeneratorV1(db, no_commits, no_users, seed, sign)
        case "invalid_goc_given":
            generator = InvalidRepoGeneratorGoc(db, no_commits, no_users, seed, sign)
        case _:
            print(f"generator type {type} invalid!")
            exit(1)
    generator.generate()
    print(f"repository successfully generated at {db.absolute()}")

if __name__ == "__main__":
    generate_repo()