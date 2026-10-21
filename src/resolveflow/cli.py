import argparse
import getpass
import os

from alembic import command
from alembic.config import Config
from langgraph.checkpoint.postgres import PostgresSaver
from sqlalchemy import select

from resolveflow.api.auth import ROLES
from resolveflow.api.security import password_hash, verify_password
from resolveflow.settings import get_settings
from resolveflow.storage.db import sessions
from resolveflow.storage.models import Account, AuthSession
from resolveflow.storage.seed import seed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["init", "seed", "create-user"])
    parser.add_argument("--username")
    parser.add_argument("--role", choices=list(ROLES))
    args = parser.parse_args()
    if args.command == "create-user":
        if not args.username or not args.role:
            parser.error("create-user requires --username and --role")
        password = os.getenv("RESOLVEFLOW_USER_PASSWORD") or getpass.getpass("New user password: ")
        if len(password) < 16:
            parser.error("Use a password of at least 16 characters")
        with sessions().begin() as s:
            if s.get(Account, args.username):
                parser.error("That username already exists")
            s.add(
                Account(
                    username=args.username,
                    password_hash=password_hash(password),
                    role=args.role,
                    workspace="demo",
                    customers=list(ROLES[args.role]),
                )
            )
        print("Named account created.")
        return
    if args.command == "init":
        command.upgrade(Config("alembic.ini"), "head")
        with PostgresSaver.from_conn_string(get_settings().checkpoint_url) as saver:
            saver.setup()
    with sessions().begin() as s:
        seed(s)
        cfg = get_settings()
        for role, customers in ROLES.items():
            password = getattr(cfg, f"{role}_password").get_secret_value()
            if not password:
                continue
            account = s.get(Account, role)
            if not account:
                s.add(
                    Account(
                        username=role,
                        password_hash=password_hash(password),
                        role=role,
                        workspace="demo",
                        customers=list(customers),
                    )
                )
            elif not verify_password(password, account.password_hash):
                account.password_hash = password_hash(password)
                for active in s.scalars(select(AuthSession).where(AuthSession.actor == role)):
                    active.revoked = True
    print("Fictional sandbox initialized; persistent checkpoints enabled.")


if __name__ == "__main__":
    main()
