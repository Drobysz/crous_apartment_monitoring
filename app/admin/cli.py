from __future__ import annotations

import argparse
import asyncio
import getpass
import sys

from sqlalchemy import select

from app.admin.security import PasswordPolicyError, hash_password, normalize_username
from app.db.models import Admin
from app.db.session import SessionLocal


async def create_superadmin(args: argparse.Namespace) -> int:
    try:
        username, username_key = normalize_username(args.username)
        password = (
            sys.stdin.readline().rstrip("\n")
            if args.password_stdin
            else getpass.getpass("Password: ")
        )
        if not password:
            raise PasswordPolicyError("Password cannot be empty")
        password_hash = await hash_password(password)
    except (ValueError, PasswordPolicyError) as error:
        print(f"create-superadmin failed: {error}", file=sys.stderr)
        return 2
    async with SessionLocal() as session:
        existing = await session.scalar(select(Admin).where(Admin.username_key == username_key))
        if existing is not None and not args.update_existing:
            print(
                "create-superadmin failed: username already exists (use --update-existing to change it)",
                file=sys.stderr,
            )
            return 1
        if existing is None:
            session.add(
                Admin(
                    name=args.name.strip(),
                    username=username,
                    username_key=username_key,
                    password_hash=password_hash,
                    role="superadmin",
                    is_active=True,
                )
            )
            action = "created"
        else:
            existing.name = args.name.strip()
            existing.username = username
            existing.password_hash = password_hash
            existing.role = "superadmin"
            existing.is_active = True
            action = "updated"
        await session.commit()
    print(f"Superadmin {action}: {username}")
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="python -m app.admin.cli")
    commands = root.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create-superadmin", help="Create a superadmin account")
    create.add_argument("--name", required=True)
    create.add_argument("--username", required=True)
    create.add_argument(
        "--password-stdin", action="store_true", help="Read the password from standard input"
    )
    create.add_argument(
        "--update-existing", action="store_true", help="Explicitly update an existing username"
    )
    return root


def main() -> int:
    args = parser().parse_args()
    if args.command == "create-superadmin":
        return asyncio.run(create_superadmin(args))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
