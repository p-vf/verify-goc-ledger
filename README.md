### Verify GOC Ledger over 2P-BFT-Log
Goal of this this project was the optimization of Invariant Verification for Safe Replication of BFT-Logs.

### How to run
To be able to run the reproduction script, you have to have [uv](https://docs.astral.sh/uv/getting-started/installation/#installation-methods) installed.
Additionally the openssh client must be installed.

To run the script you can run the file `./repro.sh` located in the root of this project.
You may have to set the permissions to run this file (i.e. `chmod +x ./repro.sh`) before being able to run it.
This will take a while to finish and after it is finished, two folders with results will have appeared in the root directory of this project.