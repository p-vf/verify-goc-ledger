from main import ValidRepoGeneratorV1, ValidRepoGeneratorPareto, ValidRepoGeneratorParetoAckDelayed
from pathlib import Path

def main():
    valid_v1_path = Path(f"./benchmarks/valid_v1/")
    valid_pareto_path = Path(f"./benchmarks/valid_pareto/")
    valid_pareto_ack_delayed_path = Path(f"./benchmarks/valid_pareto_ack_delayed/")
    for num_commits in range(300, 901, 300):
        # g = ValidRepoGeneratorV1(valid_v1_path/f"db{num_commits:03}", num_commits, 10)
        # if not g.generate():
        #     print("failed to generate valid_v1")
        # g = ValidRepoGeneratorPareto(valid_pareto_path/f"db{num_commits:03}", num_commits, 10, k=5)
        # if not g.generate():
        #     print("failed to generate valid_pareto")
        g = ValidRepoGeneratorParetoAckDelayed(valid_pareto_ack_delayed_path/f"{num_commits:03}", num_commits, 10, k=5, ack_delay=20)
        if not g.generate():
            print("failed to generate valid_pareto_ack_delayed")