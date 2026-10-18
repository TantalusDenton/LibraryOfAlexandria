from datetime import timedelta

import jwt
from fastapi import Depends, HTTPException, Request
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db, now
from .models import BookProject, User

password_hasher = PasswordHash.recommended()


def token(user_id):
    return jwt.encode(
        {"sub": user_id, "exp": now() + timedelta(days=7)}, settings().jwt_secret, algorithm="HS256"
    )


def current_user(request: Request, db: Session = Depends(get_db)):
    value = request.cookies.get("alexandria_session")
    if request.headers.get("Authorization", "").startswith("Bearer "):
        value = request.headers["Authorization"][7:]
    try:
        payload = jwt.decode(value or "", settings().jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "Sign in to continue")
    user = db.get(User, payload["sub"])
    if not user:
        raise HTTPException(401, "Session no longer valid")
    return user


def owned(db: Session, project_id, user_id):
    project = db.scalar(
        select(BookProject).where(BookProject.id == project_id, BookProject.user_id == user_id)
    )
    if not project:
        raise HTTPException(404, "Book not found")
    return project
