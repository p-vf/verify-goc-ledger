from main import ValidRepoGeneratorV1, ValidRepoGeneratorPareto
from pathlib import Path
import os

def main():
    valid_v1_path = Path(f"./benchmarks/valid_v1/")
    valid_pareto_path = Path(f"./benchmarks/valid_pareto/")
    for num_commits in range(200, 601, 200):
        g = ValidRepoGeneratorV1(valid_v1_path/f"db{num_commits:03}", num_commits, 10)
        if not g.generate():
            print("failed to generate valid_v1")
        g = ValidRepoGeneratorPareto(valid_pareto_path/f"db{num_commits:03}", num_commits, 10, k=5)
        if not g.generate():
            print("failed to generate valid_pareto")