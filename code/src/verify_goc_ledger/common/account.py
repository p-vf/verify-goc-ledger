from __future__ import annotations

from common.datastructures import Commit
from enum import Enum
from common.misc import pformat_commit_id

type Ledger = dict[bytes, Account]
type Frontier = dict[bytes, Log]

class MessageType(Enum):
    DELTA_ACC = 1
    FORK_PROOF = 2 # TODO remove this
    BYZ_ACK = 3

class Log:
    def __init__(self, author: bytes, last_non_forked: Commit, account=None):
        self.author: bytes = author
        if account is None:
            self.account = Account(author)
        else:
            self.account = account
        # The following two are assumed to consist of valid commits
        self.last_non_forked: Commit = last_non_forked
        self.fork_proof: set[Commit] = set()
        self.acked_last_non_forked: bool = True

    def __str__(self):
        return f"Log(author: {self.author}, last: {pformat_commit_id(self.last_non_forked.id)}, fork_proof: {self.fork_proof}, {self.account})"

    def __repr__(self):
        return self.__str__()

class Account:
    id: bytes
    created: int
    destroyed: int
    acked: dict[bytes, int]
    given: dict[bytes, int]
    def __init__(self, id: bytes, created: int =0, destroyed: int =0, acked: dict[bytes, int] | None =None, given: dict[bytes, int] | None =None):
        if acked is None:
            acked = dict()
        if given is None:
            given = dict()
        self.id = id
        self.created = created
        self.destroyed = destroyed
        self.acked = acked
        self.given = given

    def __repr__(self):
        return f"Account(" +\
            f"author: {self.id}, " +\
            f"c: {self.created}, " +\
            f"d: {self.destroyed}, " +\
            f"g: {self.given}, " +\
            f"a: {self.acked}, " +\
            f"b: {self.balance()})"

    def give(self, amount, to_id):
        """returns delta account"""
        if to_id not in self.given.keys():
            self.given[to_id] = 0
        self.given[to_id] += amount
        return Account(self.id, given={to_id: self.given[to_id]})

    def ack(self, amount, from_id):
        """returns delta account"""
        if from_id not in self.acked.keys():
            self.acked[from_id] = 0
        self.acked[from_id] += amount
        return Account(self.id, acked={from_id: self.acked[from_id]})

    def create(self, amount):
        """returns delta account"""
        self.created += amount
        return Account(self.id, created=self.created)

    def destroy(self, amount):
        """returns delta account"""
        self.destroyed += amount
        return Account(self.id, destroyed=self.destroyed)

    def balance(self):
        return self.created - self.destroyed + sum(self.acked.values()) - sum(self.given.values())

    def merge(self, other: Account):
        # print(f"called merge with {other!r}")
        # print(f"before: {self!r}")
        self.created = max(self.created, other.created)
        self.destroyed = max(self.destroyed, other.destroyed)
        for name, amount in self.acked.items():
            if name in other.acked:
                self.acked[name] = max(amount, other.acked[name])
        for name, amount in other.acked.items():
            if name in self.acked:
                self.acked[name] = max(self.acked[name], amount)
            else:
                self.acked[name] = amount
        for name, amount in self.given.items():
            if name in other.given:
                self.given[name] = max(amount, other.given[name])
        for name, amount in other.given.items():
            if name in self.given:
                self.given[name] = max(self.given[name], amount)
            else:
                self.given[name] = amount
        # print(f"after: {self!r}")

