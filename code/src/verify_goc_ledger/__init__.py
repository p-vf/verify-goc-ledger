def main() -> None:
    print("Hello from generate-repo!")

import sys
from pathlib import Path
parent_folder = Path(__file__).resolve().parent
print(parent_folder)
sys.path.insert(0, str(parent_folder))

from generate_repo.main import generate_repo
from verification.git_cli.test_git_cli import main as verify_repo_git_cli
