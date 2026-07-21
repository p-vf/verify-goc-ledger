from main import ValidRepoGeneratorParetoAckDelayed
from pathlib import Path

def main():
    valid_pareto_ack_delayed_path = Path(f"./storage_benchmarks/valid_pareto_ack_delayed/")
    num_commits = 1500
    g4 = ValidRepoGeneratorParetoAckDelayed(valid_pareto_ack_delayed_path/f"acc_as_msg_unnecessary_deps", num_commits, 100, k=5, ack_delay=20, acc_as_tree_storage=False, unnecessary_deps=True)
    if not g4.generate():
        print("failed to generate valid_pareto_ack_delayed")
    g3 = ValidRepoGeneratorParetoAckDelayed(valid_pareto_ack_delayed_path/f"acc_as_tree_unnecessary_deps", num_commits, 100, k=5, ack_delay=20, acc_as_tree_storage=True, unnecessary_deps=True)
    if not g3.generate():
        print("failed to generate valid_pareto_ack_delayed")
    g2 = ValidRepoGeneratorParetoAckDelayed(valid_pareto_ack_delayed_path/f"acc_as_tree", num_commits, 100, k=5, ack_delay=20, acc_as_tree_storage=True)
    if not g2.generate():
        print("failed to generate valid_pareto_ack_delayed")
    g = ValidRepoGeneratorParetoAckDelayed(valid_pareto_ack_delayed_path/f"acc_as_msg", num_commits, 100, k=5, ack_delay=20)
    if not g.generate():
        print("failed to generate valid_pareto_ack_delayed")