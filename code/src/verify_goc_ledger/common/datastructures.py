from common.misc import pformat_commit_id

class Commit:
    """
    Here we always assume that author and committer are the same. The check has
    to be done by the commit parser.
    """
    def __init__(self, id, tree, parents, author_name, author_email, author_date, body):
        self.id: bytes = id
        self.tree: bytes = tree
        self.parents: list[bytes] = parents
        self.author_name: bytes = author_name
        self.author_email: bytes = author_email
        self.author_date: bytes = author_date
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
