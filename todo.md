### Next steps
- general:
  - [ ] identify the messy parts of the codebase
  - [ ] clean up found messy parts
- initial get_delta_acc:
  - [ ] implement the retrieval of the blobs with push-stream modules
    - structure of the first push-stream: `treedict = push(commit_id -> subprocess "git ls-tree -r" -> splitline -> validate_treeline_syntax_and_parse[tuple[Bid, Path]] -> reduce_to_dict[dict[Bid, set[Path]]])` (could also be implemented without push-stream using subprocess.Popen.communicate)
    - structure of the second push-stream: `parsed_tree = values(treedict) -> subprocess "git cat-file --batch" -> blob_parser[tuple[Bid, Content]] -> decode_blob -> reduce_to_dict_2(treedict)[dict[Path, int]]`
      - `blob_parser` can be implemented using a map module with an impure
        function (a class implementing the `__call__` method)
    - [ ] integrate the push-stream modules from Erick's repository
    - [ ] implement the second push-stream
    - [ ] implement the first push-stream (maybe)
- [ ] implement fork check:
  - [x] extend repo generation to allow for different message types
  (fork proof, fork acknowledgement, ledger message)
  - [x] extend repo parsing to allow for the different message types
  - [x] extend log data structure to accommodate for forks and their
        acknowledgement
    - [x] add and correctly update a valid frontier that
          keeps track of all valid messages even after a fork
    - [x] change check_if_already_verified to take the new valid frontier and
          the list of verified fork proofs into account
    - [x] somehow add a fork_acknowledgement field that keeps track of what forks
          the author has acknowledged
  - [x] implement checks that must be satisfied when considering forks
    - [x] check for valid fork proof commits
    - [x] check for valid fork acknowledgements
    - [x] if there is a fork that the author has not acknowledged, the author
          must - in the next message - acknowledge said fork
- [ ] implement signature check and check performance differences
  - the signature only has to be checked on commits that are of type FORK_ACK
    or DELTA_ACC
  - if a message is invalid but signed correctly, we have to handle this somehow
    differently (update a git reference that tracks the invalid commit)

### Invariant Checks
- [ ] implement check of signature
- [ ] implement fork proof checks

### Features of repo generation
- [ ] introduce root message type (start of a log)

### Chores
- [ ] replace variables of type `bytes` with variables of type `str` 
where it makes sense
- [ ] generation of repos: prevent git from creating unnecessary hooks (scripts)

### Future Ideas
- [x] create benchmarks with a more realistic distribution of
transactions per author (heavy-tailed).
- [ ] Recreate test scenario of real transactions

### Notes
- The implementation of `read_blob_fast` is buggy: It blocks whenever some
  bytes are in the blob, for example '\\r'.
- What invariants hold for the GOC-Ledger after a fork?