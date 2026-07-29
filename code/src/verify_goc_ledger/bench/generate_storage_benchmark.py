from common.misc import run_cmd
from main import ValidRepoGeneratorParetoAckDelayed
from pathlib import Path
import subprocess
import itertools
import os

benchmark_path = Path(f"./storage_benchmarks/valid_pareto_ack_delayed/")
num_commits = 1000
num_authors = 100

def main():
    def get_number(res: bytes):
        return int(res.split(b"\t")[0])
    with open(benchmark_path/"results.csv", "wt+") as f:
        f.write("name,apparent size,real size,apparent size after compression,real size after compression\n")
        for acc_as_tree, unnecessary_deps in itertools.product([True, False], [True, False]):
            name = "account as " + ("tree" if acc_as_tree else "msg") + (" with unnecessary deps" if unnecessary_deps else "")
            fname = name.replace(" ", "_")
            g = ValidRepoGeneratorParetoAckDelayed(benchmark_path/fname, num_commits, num_authors, k=5, ack_delay=20, acc_as_tree_storage=acc_as_tree, unnecessary_deps=unnecessary_deps)
            if not g.generate():
                print("failed to generate valid_pareto_ack_delayed")
            else:
                repo_dir_str = str(benchmark_path/fname/".git/")
                du_cmd = ["du", repo_dir_str, "-s"]
                size_apparent = get_number(run_cmd(du_cmd + ["--apparent-size"]))
                size_real = get_number(run_cmd(du_cmd))
                subprocess.run(["git", "gc"], env=(os.environ | {"GIT_DIR": repo_dir_str}), capture_output=True)
                size_apparent_compressed = get_number(run_cmd(du_cmd + ["--apparent-size"]))
                size_real_compressed = get_number(run_cmd(du_cmd))
                f.write(f"{name},{size_apparent},{size_real},{size_apparent_compressed},{size_real_compressed}\n")
