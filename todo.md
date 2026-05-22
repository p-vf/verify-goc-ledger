### Next steps
- initial get_delta_acc:
  - [ ] specify blob content format using some kind of encoding (base64
  or alike)
  - [ ] use ls-tree -r to get the blobs
  - [ ] use cat-file --batch to get the content of the blobs
- [ ] implement fork check:
  - [ ] extend repo generation to allow for different message types
  (fork proof, fork acknowledgement, ledger message)
  - [ ] extend repo parsing to allow for the different message types
  - [ ] extend log datastructure to accomodate for forks and their
  acknowledgement
  - [ ] implement check itself
- [ ] implement signature check and check performance differences

### Invariant Checks
- [ ] implement check of signature
- [ ] implement fork proof checks

### Features of repo generation
- [ ] introduce root message type (start of a log)
- [ ] allow generation of fork proofs
- [x] allow generation of empty delta account as git objects
- [x] allow generation of empty given/acked fields in delta account as git 
  objects

### Chores
- [x] replace all instances of "delta state" with "delta account" where 
it makes sense
- [ ] replace variables of type `bytes` with variables of type `str` 
where it makes sense
- [ ] generation of repos: prevent git from creating unnecessary hooks (scripts)

### Future Ideas
- [x] create benchmarks with a more realistic distribution of
transactions per author (heavy-tailed).
- [ ] Recreate test scenario of real transactions
