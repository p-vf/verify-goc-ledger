from main import ValidRepoGeneratorParetoAckDelayed
from pathlib import Path

def main():
    valid_pareto_ack_delayed_path = Path(f"./benchmarks/valid_pareto_ack_delayed/")
    for num_commits in range(300, 901, 300):
        g = ValidRepoGeneratorParetoAckDelayed(valid_pareto_ack_delayed_path/f"{num_commits:03}", num_commits, 30, k=5, ack_delay=20)
        if not g.generate():
            print("failed to generate valid_pareto_ack_delayed")