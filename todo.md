### Next steps
- [ ] report: Write down findings for extension of 2P-BFT-Log:
  - [ ] Read the relevant part of the paper carefully
  - [ ] Write down the example and what the problem is, and compare it 
  to the description in the paper
  - [ ] introduce a new message type (FORK_ACKNOWLEDGEMENT)
  - [ ] write down how the example would be correct
- [ ] verifier: Implement caching of last ledger state of each author
- [x] verifier: Implement checks for invariant M7 (monotonic dependencies): 
  - To achieve this, one could store the most recent commit this author 
  knows from each other author (could be stored in conjunction with the 
  last ledger state of each author) and then compare any dependencies to
  those. 
- [ ] benchmarks: track how much time each invariant check takes

### Invariant Checks
- [ ] implement fork proof checks

### Features of repo generation
- [ ] allow generation of fork proofs
- [ ] allow generation of empty delta account as git objects
- [ ] allow generation of empty given/acked fields in delta account as git 
objects

### Chores
- [x] replace all instances of "delta state" with "delta account" where 
it makes sense
- [ ] replace variables of type `bytes` with variables of type `str` 
where it makes sense

### Future Ideas
- [ ] create benchmarks with a more realistic distribution of 
transactions per author (heavy-tailed).
- [ ] Recreate test scenario of real transactions
