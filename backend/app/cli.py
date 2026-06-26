"""Management CLI for AllDocs."""

from __future__ import annotations

import argparse
import asyncio
import sys

from app.db.session import async_session_factory, init_db
from app.services.auth_service import AuthError, register_with_email
from app.db.models import UserRole


async def _create_admin(email: str, password: str) -> None:
    await init_db()
    async with async_session_factory() as db:
        try:
            await register_with_email(
                db,
                email=email,
                password=password,
                display_name="Admin",
                role=UserRole.admin,
            )
            await db.commit()
        except AuthError as exc:
            if exc.status_code == 409:
                print(f"Admin already exists for {email}", file=sys.stderr)
                return
            raise
    print(f"Created admin user: {email}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_admin = subparsers.add_parser("create-admin", help="Create an admin account")
    create_admin.add_argument("--email", required=True)
    create_admin.add_argument("--password", required=True)

    args = parser.parse_args()
    if args.command == "create-admin":
        asyncio.run(_create_admin(args.email, args.password))


if __name__ == "__main__":
    main()
