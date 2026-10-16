# ATLAS — Personal cloud drive server
# Copyright (C) 2026-Present  DarThunder
# SPDX-License-Identifier: AGPL-3.0-or-later

import hashlib
import hmac
import logging
import os
import secrets
from datetime import timedelta

from fastapi import Depends, HTTPException, Request
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

import config
from db import SessionLocal, User, UserSession, get_db, utcnow

log = logging.getLogger("atlas.security")

COOKIE_NAME = "atlas_session"
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_hex, dk_hex = stored.split("$")
        if scheme != "scrypt":
            return False
        dk = hashlib.scrypt(
            password.encode(), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1, dklen=32
        )
        return hmac.compare_digest(dk.hex(), dk_hex)
    except Exception:
        return False

DUMMY_HASH = hash_password(secrets.token_hex(8))

def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db: Session, user: User) -> tuple[str, int]:
    db.execute(delete(UserSession).where(UserSession.expires_at < utcnow()))
    token = secrets.token_urlsafe(32)
    ttl = timedelta(days=config.SESSION_TTL_DAYS)
    db.add(UserSession(token_hash=_hash_token(token), user_id=user.id, expires_at=utcnow() + ttl))
    db.commit()
    return token, int(ttl.total_seconds())


def destroy_session(db: Session, token: str | None) -> None:
    if token:
        db.execute(delete(UserSession).where(UserSession.token_hash == _hash_token(token)))
        db.commit()


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(COOKIE_NAME)
    if token:
        row = db.get(UserSession, _hash_token(token))
        if row is not None and row.expires_at > utcnow():
            user = db.get(User, row.user_id)
            if user is not None:
                return user
    raise HTTPException(401, "No autenticado")


def csrf_guard(request: Request) -> None:
    if request.method not in _SAFE_METHODS and request.headers.get("X-Atlas") != "1":
        raise HTTPException(403, "Falta la cabecera X-Atlas")

def seed_admin() -> None:
    with SessionLocal() as db:
        if db.scalar(select(User.id).limit(1)) is not None:
            return
        password = config.ADMIN_PASSWORD
        generated = False
        if not password:
            password = secrets.token_urlsafe(12)
            generated = True
        db.add(User(username=config.ADMIN_USER, password_hash=hash_password(password)))
        db.commit()
    if generated:
        log.warning(
            "ATLAS_ADMIN_PASSWORD no definido. Usuario inicial '%s' con contraseña generada: %s",
            config.ADMIN_USER, password,
        )
    else:
        log.info("Usuario inicial '%s' creado", config.ADMIN_USER)
