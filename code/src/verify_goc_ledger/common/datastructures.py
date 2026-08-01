from common.misc import pformat_commit_id
from enum import Enum

type Ledger = dict[bytes, Account]

class MessageType(Enum):
    ACCOUNT = 1
    BYZ_ACK = 2

class Summary:
    def __init__(self, author: bytes):
        self.frontier: dict[bytes, set[bytes]] = dict()
        self.byzantine: set[bytes] = set()
        self.byz_acked: set[bytes] = set()
        self.account: Account = Account(author)
        self.recieved: dict[bytes, int] = dict()


class Commit:
    """
    Here we always assume that author and committer are the same. The check has
    to be done by the commit parser.
    """
    def __init__(self, id, tree, parents, author_name, author_email, author_date, signature_status, body):
        self.id: bytes = id
        self.tree: bytes = tree
        self.parents: list[bytes] = parents
        self.author_name: bytes = author_name
        self.author_email: bytes = author_email
        self.author_date: bytes = author_date
        self.signature_status: bytes = signature_status
        self.signature_valid: bool | None = None # will be filled when signature is checked
        self.body: bytes = body

    def __eq__(self, other):
        if type(other) != type(self):
            return False
        return self.id == other.id

    def __hash__(self):
        return hash(self.id)

    def __repr__(self):
        return self.__str__()

    def __str__(self):
        return f"Commit(id: {pformat_commit_id(self.id)}, author: {self.author_name}, body: {self.body}, parents: {", ".join(map(lambda x: pformat_commit_id(x), self.parents))})"

class Child:
    def __init__(self, id, type, name):
        self.id: bytes = id
        self.type: bytes = type
        self.name: bytes = name

class Tree:
    def __init__(self, id, children):
        self.id = id
        self.children: list[Child] = children

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

    def merge(self, other: "Account"):
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
