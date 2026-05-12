from __future__ import annotations

from common.datastructures import Commit

type Ledger = dict[bytes, Account]

def update_frontier(account: Account, frontier: dict[bytes, Log], last_message: Commit):
    """ASSUMPTION accounts get added in reverse topological order!! (relevant for message_id)"""
    if account.id in frontier:
        frontier[account.id].account.merge(account)
        frontier[account.id].last_non_forked = last_message
    else:
        frontier[account.id] = Log(account.id, last_message)
        frontier[account.id].last_non_forked = last_message
        frontier[account.id].account = account

class Log:
    def __init__(self, author: bytes, last_non_forked: Commit):
        self.author: bytes = author
        self.account = Account(author)
        # The following two are assumed to consist of valid commits
        self.last_non_forked: Commit = last_non_forked
        self.fork_frontier: set[Commit] = set()
    
    def __str__(self):
        return f"Log({self.author}, {self.last_non_forked.id})"
    
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
        return f"{self.id}:\n" +\
            f"  created: {self.created}\n" +\
            f"  destroyed: {self.destroyed}\n" +\
            f"  given: {self.given}\n" +\
            f"  acked: {self.acked}\n" +\
            f"  balance: {self.balance()}\n"

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
                
