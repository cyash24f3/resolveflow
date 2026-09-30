import argparse

from alembic import command
from alembic.config import Config
from langgraph.checkpoint.postgres import PostgresSaver

from resolveflow.settings import get_settings
from resolveflow.storage.db import sessions
from resolveflow.storage.seed import seed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["init", "seed"])
    args = parser.parse_args()
    if args.command == "init":
        command.upgrade(Config("alembic.ini"), "head")
        with PostgresSaver.from_conn_string(get_settings().checkpoint_url) as saver:
            saver.setup()
    with sessions().begin() as s:
        seed(s)
    print("Fictional sandbox initialized; persistent checkpoints enabled.")


if __name__ == "__main__":
    main()
