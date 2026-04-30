import time


class Commit:
    def __init__(self, id, tree, parents, author_name, author_email, author_date, committer_name, committer_email, committer_date, body):
        self.id: bytes = id
        self.tree: bytes = tree
        self.parents: list[bytes] = parents
        self.author_name: bytes = author_name
        self.author_email: bytes = author_email
        self.author_date: bytes = author_date
        self.committer_name: bytes = committer_name
        self.committer_email: bytes = committer_email
        self.committer_date: bytes = committer_date
        self.body: bytes = body
    
    def author_committer_equal(self):
        return self.author_name == self.committer_name and self.author_email == self.committer_email and self.author_date == self.committer_date

class Child:
    def __init__(self, id, type, name):
        self.id: bytes = id
        self.type: bytes = type
        self.name: bytes = name

class Tree:
    def __init__(self, id, children):
        self.id = id
        self.children: list[Child] = children

class Statistics:
    def __init__(self):
        self.no_commit_accesses = 0
        self.no_blob_accesses = 0
        self.no_tree_accesses = 0
        self.no_rev_list_calls = 0
        self._start_time = time.perf_counter_ns()
        self.time = 0
    
    def start(self):
        self._start_time = time.perf_counter_ns()
    
    def reset(self):
        self.no_commit_accesses = 0
        self.no_blob_accesses = 0
        self.no_tree_accesses = 0
        self.no_rev_list_calls = 0
    
    def end(self):
        self.time = (self._start_time - time.perf_counter_ns()) / 1000000
