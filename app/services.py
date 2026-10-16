# ATLAS — Personal cloud drive server
# Copyright (C) 2026-Present  DarThunder
# SPDX-License-Identifier: AGPL-3.0-or-later

import os
import re

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from db import Node

SQL_BATCH = 500
_BAD_NAME = re.compile(r"[\x00-\x1f/\\]")

def batched(seq: list, n: int = SQL_BATCH):
    for i in range(0, len(seq), n):
        yield seq[i : i + n]

def clean_name(raw: str) -> str:
    name = _BAD_NAME.sub("_", raw).strip()
    if name in ("", ".", ".."):
        raise HTTPException(400, "Nombre inválido")
    if len(name) > 255:
        raise HTTPException(400, "Nombre demasiado largo (máx 255)")
    return name

def clean_upload_name(raw: str | None) -> str:
    name = _BAD_NAME.sub("_", os.path.basename((raw or "").replace("\\", "/"))).strip()
    if name in ("", ".", ".."):
        return "archivo"
    if len(name) > 255:
        stem, ext = os.path.splitext(name)
        name = stem[: 255 - len(ext)] + ext
    return name

def make_sort_key(name: str, kind: str) -> str:
    return ("0" if kind == "folder" else "1") + name.casefold()

def parent_clause(parent_id: int | None):
    return Node.parent_id.is_(None) if parent_id is None else Node.parent_id == parent_id

def name_taken(db: Session, owner_id: int, parent_id: int | None, name: str,
               exclude_id: int | None = None) -> bool:
    key = name.casefold()
    q = select(Node.id).where(
        Node.owner_id == owner_id,
        parent_clause(parent_id),
        Node.trashed_at.is_(None),
        Node.sort_key.in_(["0" + key, "1" + key]),
    )
    if exclude_id is not None:
        q = q.where(Node.id != exclude_id)
    return db.scalar(q.limit(1)) is not None

def unique_name(db: Session, owner_id: int, parent_id: int | None, name: str) -> str:
    if not name_taken(db, owner_id, parent_id, name):
        return name
    stem, ext = os.path.splitext(name)
    i = 1
    while True:
        candidate = f"{stem} ({i}){ext}"
        if not name_taken(db, owner_id, parent_id, candidate):
            return candidate
        i += 1

def get_node(db: Session, owner_id: int, node_id: int, trashed: bool | None = False) -> Node:
    q = select(Node).where(Node.id == node_id, Node.owner_id == owner_id)
    if trashed is False:
        q = q.where(Node.trashed_at.is_(None))
    elif trashed is True:
        q = q.where(Node.trashed_at.is_not(None))
    node = db.scalar(q)
    if node is None:
        raise HTTPException(404, "No encontrado")
    return node

def require_folder(db: Session, owner_id: int, parent_id: int | None) -> Node | None:
    if parent_id is None:
        return None
    parent = get_node(db, owner_id, parent_id)
    if parent.kind != "folder":
        raise HTTPException(400, "El destino no es una carpeta")
    return parent

def descendants(db: Session, owner_id: int, root_id: int) -> list[Node]:
    out: list[Node] = []
    frontier = [root_id]
    while frontier:
        nxt: list[Node] = []
        for batch in batched(frontier):
            nxt.extend(db.scalars(
                select(Node).where(Node.owner_id == owner_id, Node.parent_id.in_(batch))
            ).all())
        out.extend(nxt)
        frontier = [n.id for n in nxt]
    return out

def is_inside(db: Session, owner_id: int, node_id: int, candidate_parent: int | None) -> bool:
    cur = candidate_parent
    for _ in range(10_000):
        if cur is None:
            return False
        if cur == node_id:
            return True
        cur = db.scalar(select(Node.parent_id).where(Node.id == cur, Node.owner_id == owner_id))
    return True

def breadcrumbs(db: Session, owner_id: int, node: Node) -> list[Node]:
    chain = [node]
    cur = node.parent_id
    while cur is not None and len(chain) < 10_000:
        parent = db.scalar(select(Node).where(Node.id == cur, Node.owner_id == owner_id))
        if parent is None:
            break
        chain.append(parent)
        cur = parent.parent_id
    chain.reverse()
    return chain

def purge(db: Session, nodes: list[Node]) -> list[int]:
    ids = [n.id for n in nodes]
    blob_ids = [n.blob_id for n in nodes if n.kind == "file" and n.blob_id is not None]
    for batch in batched(ids):
        db.execute(delete(Node).where(Node.id.in_(batch)))
    return blob_ids

def can_inline(mimetype: str | None) -> bool:
    m = (mimetype or "").split(";")[0].strip().lower()
    if m == "image/svg+xml":
        return False
    return m.startswith(("image/", "video/", "audio/")) or m == "application/pdf"
