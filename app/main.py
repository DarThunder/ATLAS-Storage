# ATLAS — Personal cloud drive server
# Copyright (C) 2026-Present  DarThunder
# SPDX-License-Identifier: AGPL-3.0-or-later

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles

from blob import close_blob
from db import init_db
from routes import auth, files, nodes
from security import csrf_guard, seed_admin

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

UI_CSP = (
    "default-src 'self'; img-src 'self' data: blob:; media-src 'self'; "
    "frame-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'"
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    seed_admin()
    try:
        yield
    finally:
        close_blob()


app = FastAPI(title="ATLAS", lifespan=lifespan, dependencies=[Depends(csrf_guard)])

app.include_router(auth.router, prefix="/api")
app.include_router(nodes.router, prefix="/api")
app.include_router(files.router, prefix="/api")


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    if not request.url.path.startswith("/api/"):
        response.headers.setdefault("Content-Security-Policy", UI_CSP)
    return response

app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=int(os.getenv("PORT", "8082")))
