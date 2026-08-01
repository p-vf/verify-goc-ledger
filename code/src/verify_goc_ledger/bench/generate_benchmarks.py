from main import ValidRepoGeneratorParetoAckDelayed
from pathlib import Path
import argparse

def main():
    p = argparse.ArgumentParser()
    p.add_argument("-s", "--start", type=int, default=300, help="number of commits start value")
    p.add_argument("-e", "--end", type=int, default=901, help="number of commits end value")
    p.add_argument("-d", "--step", type=int, default=300, help="number of commits step value")
    p.add_argument("-a", "--num-authors", type=int, default=30, help="number of authors")
    args = p.parse_args()
    start = args.start
    end = args.end
    step = args.step
    num_authors = args.num_authors
    valid_pareto_ack_delayed_path = Path(f"./benchmarks/valid_pareto_ack_delayed/")
    for num_commits in range(start, end, step):
        g = ValidRepoGeneratorParetoAckDelayed(valid_pareto_ack_delayed_path/f"{num_commits:03}", num_commits, num_authors, k=5, ack_delay=20)
        if not g.generate():
            print("failed to generate valid_pareto_ack_delayed")