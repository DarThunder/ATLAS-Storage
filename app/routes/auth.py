# ATLAS — Personal cloud drive server
# Copyright (C) 2026-Present  DarThunder
# SPDX-License-Identifier: AGPL-3.0-or-later

import time
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

import config
from db import User, get_db
from schemas import LoginIn, UserOut
from security import (
    COOKIE_NAME, DUMMY_HASH, create_session, current_user, destroy_session, verify_password, hash_password
)

router = APIRouter(prefix="/auth", tags=["auth"])

_FAILS: dict[str, list[float]] = defaultdict(list)
_MAX_FAILS = 10
_WINDOW = 300.0


def _ip(request: Request) -> str:
    return request.client.host if request.client else "?"


def _recent_fails(ip: str) -> list[float]:
    now = time.monotonic()
    fresh = [t for t in _FAILS[ip] if now - t < _WINDOW]
    _FAILS[ip] = fresh
    return fresh

@router.post("/register", response_model=UserOut, status_code=201)
def register(body: LoginIn, db: Session = Depends(get_db)):
    existing_user = db.scalar(select(User).where(User.username == body.username))
    if existing_user:
        raise HTTPException(400, "El nombre de usuario ya está registrado")

    new_user = User(
        username=body.username,
        password_hash=hash_password(body.password)
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return new_user

@router.post("/login", response_model=UserOut)
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    ip = _ip(request)
    if len(_recent_fails(ip)) >= _MAX_FAILS:
        raise HTTPException(429, "Demasiados intentos. Espera unos minutos.")

    user = db.scalar(select(User).where(User.username == body.username))
    ok = verify_password(body.password, user.password_hash if user else DUMMY_HASH)
    if not user or not ok:
        _FAILS[ip].append(time.monotonic())
        raise HTTPException(401, "Usuario o contraseña incorrectos")

    _FAILS.pop(ip, None)
    token, max_age = create_session(db, user)
    response.set_cookie(
        COOKIE_NAME, token, max_age=max_age, httponly=True, samesite="lax",
        secure=config.COOKIE_SECURE, path="/",
    )
    return user


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    destroy_session(db, request.cookies.get(COOKIE_NAME))
    response.delete_cookie(COOKIE_NAME, path="/")


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user
