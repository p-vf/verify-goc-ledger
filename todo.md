### Next steps
- initial get_delta_acc:
  - [x] specify blob content format using some kind of encoding (base64
  or alike)
  - [x] use ls-tree -r to get the blobs
  - [x] use cat-file --batch to get the content of the blobs (see
    [Notes](#notes) on `read_blob_fast`)
- [ ] implement fork check:
  - [x] extend repo generation to allow for different message types
  (fork proof, fork acknowledgement, ledger message)
  - [x] extend repo parsing to allow for the different message types
  - [ ] extend log data structure to accommodate for forks and their
  acknowledgement
    - [ ] add and correctly update a valid fork frontier to each log that
          keeps track of all valid messages after a fork
    - [ ] add a list of verified fork proofs to the verifier
    - [ ] change check_if_already_verified to take the valid fork frontiers of
          all logs and the list of verified fork proofs into account
    - [ ] somehow add a fork_acknowledgement field that keeps track of what forks
          the author has acknowledged
  - [ ] implement checks that must be satisfied when considering forks
    - [x] check for valid fork proof commits
    - [ ] check for valid fork acknowledgements
    - [ ] if there is a fork that the author has not acknowledged, the author
          must - in the next non-delta_account message - acknowledge said fork
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