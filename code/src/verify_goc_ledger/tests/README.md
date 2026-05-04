# Test structure
In this document, I document the structure of the tests.
## Goal of the Tests
In each test, a specific invariant check is verified. This means for each invariant check, there is (ideally) at least one test case, which should fail said check. 
## Methodology
To achieve this, a repository is generated for each testcase, together with two text files like the following:
```
testcases
├── test1
│   ├── db
│   │   └── .git
│   │       └── ...
│   ├── expected_invalid.txt
│   └── expected_valid.txt
├── test2
:   └── ...
:
```
In the two text files `expected_valid.txt` and `expected_invalid.txt`, the commit hashes corresponding to commits are listed which are valid and invalid respectively (separated by a newline character). These commit hashes are lexicographically ordered. 
