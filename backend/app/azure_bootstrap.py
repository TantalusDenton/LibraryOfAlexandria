"""Create the initial private studio account once, without exposing a public signup window."""

import os

from sqlalchemy import select

from .auth import password_hasher
from .db import SessionLocal
from .models import User
from .schemas import Credentials


def main():
    account = Credentials(email=os.environ["OWNER_EMAIL"], password=os.environ["OWNER_PASSWORD"])
    with SessionLocal() as db:
        if not db.scalar(select(User).where(User.email == account.email.lower())):
            db.add(User(email=account.email.lower(), password_hash=password_hasher.hash(account.password)))
            db.commit()


if __name__ == "__main__":
    main()
