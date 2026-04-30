from __future__ import annotations

type Ledger = dict[bytes, Account]

def update_ledger(account: Account, ledger: Ledger):
    if account.id in ledger:
        ledger[account.id].merge(account)
    else:
        ledger[account.id] = account

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
        """returns delta state"""
        if to_id not in self.given.keys():
            self.given[to_id] = 0
        self.given[to_id] += amount
        return Account(self.id, given={to_id: self.given[to_id]})

    def ack(self, amount, from_id):
        """returns delta state"""
        if from_id not in self.acked.keys():
            self.acked[from_id] = 0
        self.acked[from_id] += amount
        return Account(self.id, acked={from_id: self.acked[from_id]})

    def create(self, amount):
        """returns delta state"""
        self.created += amount
        return Account(self.id, created=self.created)

    def destroy(self, amount):
        """returns delta state"""
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
                
