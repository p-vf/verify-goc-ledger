from main import ValidRepoGeneratorV1
from pathlib import Path

def main():
    for num_commits in range(50, 151, 50):
        g = ValidRepoGeneratorV1(Path(f"./benchmarks/valid_v1/db{num_commits:03}"), num_commits, 10)
        g.generate()