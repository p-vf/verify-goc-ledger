from common.misc import run_cmd
from main import ValidRepoGeneratorParetoAckDelayed
from pathlib import Path
import subprocess
import itertools
import os
import argparse

benchmark_path = Path(f"./storage_benchmarks/valid_pareto_ack_delayed/")

def main():
    p = argparse.ArgumentParser()
    p.add_argument("-c", "--num-commits", type=int, default=1000, help="number of commits")
    p.add_argument("-a", "--num-authors", type=int, default=100, help="number of authors")
    p.add_argument("-o", "--output-dir", type=Path, default=Path(benchmark_path), help="where to put the result file")
    args = p.parse_args()
    num_authors = args.num_authors
    num_commits = args.num_commits
    res_dir = args.output_dir
    def get_number(res: bytes):
        return int(res.split(b"\t")[0])
    os.makedirs(res_dir, exist_ok=True)
    with open(res_dir/"results.csv", "wt+") as f:
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
