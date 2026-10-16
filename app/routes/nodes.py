# ATLAS — Personal cloud drive server
# Copyright (C) 2026-Present  DarThunder
# SPDX-License-Identifier: AGPL-3.0-or-later

import base64
import json
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session, aliased

import services as svc
from blob import get_blob
from db import Node, User, get_db, utcnow
from schemas import CrumbOut, FolderIn, NodeOut, NodeUpdate, PageOut
from security import current_user

log = logging.getLogger("atlas.nodes")
router = APIRouter(tags=["nodes"])

def _encode_cursor(node: Node) -> str:
    return base64.urlsafe_b64encode(json.dumps([node.sort_key, node.id]).encode()).decode()

def _decode_cursor(cursor: str) -> tuple[str, int]:
    try:
        key, node_id = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        if isinstance(key, str) and isinstance(node_id, int):
            return key, node_id
    except Exception:
        pass
    raise HTTPException(400, "Cursor inválido")

@router.get("/nodes", response_model=PageOut)
def list_nodes(
    parent_id: int | None = None,
    cursor: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    svc.require_folder(db, user.id, parent_id)
    q = select(Node).where(
        Node.owner_id == user.id, Node.trashed_at.is_(None), svc.parent_clause(parent_id)
    )
    if cursor:
        key, last_id = _decode_cursor(cursor)
        q = q.where(or_(Node.sort_key > key, and_(Node.sort_key == key, Node.id > last_id)))
    rows = db.scalars(q.order_by(Node.sort_key, Node.id).limit(limit + 1)).all()
    next_cursor = _encode_cursor(rows[limit - 1]) if len(rows) > limit else None
    return PageOut(items=rows[:limit], next_cursor=next_cursor)

@router.get("/nodes/{node_id}", response_model=NodeOut)
def get_node(node_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return svc.get_node(db, user.id, node_id)


@router.get("/nodes/{node_id}/path", response_model=list[CrumbOut])
def node_path(node_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    node = svc.get_node(db, user.id, node_id)
    return [CrumbOut(id=n.id, name=n.name) for n in svc.breadcrumbs(db, user.id, node)]

@router.post("/folders", response_model=NodeOut, status_code=201)
def create_folder(body: FolderIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    name = svc.clean_name(body.name)
    svc.require_folder(db, user.id, body.parent_id)
    if svc.name_taken(db, user.id, body.parent_id, name):
        raise HTTPException(409, "Ya existe un elemento con ese nombre")
    node = Node(
        owner_id=user.id, parent_id=body.parent_id, kind="folder", name=name,
        sort_key=svc.make_sort_key(name, "folder"),
    )
    db.add(node)
    db.commit()
    return node

@router.patch("/nodes/{node_id}", response_model=NodeOut)
def update_node(
    node_id: int, body: NodeUpdate,
    user: User = Depends(current_user), db: Session = Depends(get_db),
):
    node = svc.get_node(db, user.id, node_id)
    name = svc.clean_name(body.name) if body.name is not None else node.name
    parent_id = body.parent_id if "parent_id" in body.model_fields_set else node.parent_id

    if parent_id != node.parent_id:
        svc.require_folder(db, user.id, parent_id)
        if svc.is_inside(db, user.id, node.id, parent_id):
            raise HTTPException(400, "No puedes mover una carpeta dentro de sí misma")
    if (name, parent_id) != (node.name, node.parent_id):
        if svc.name_taken(db, user.id, parent_id, name, exclude_id=node.id):
            raise HTTPException(409, "Ya existe un elemento con ese nombre en el destino")

    node.name = name
    node.parent_id = parent_id
    node.sort_key = svc.make_sort_key(name, node.kind)
    db.commit()
    return node

@router.post("/nodes/{node_id}/trash", response_model=NodeOut)
def trash_node(node_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    node = svc.get_node(db, user.id, node_id)
    stamp = utcnow()
    ids = [node.id] + [d.id for d in svc.descendants(db, user.id, node.id)]
    for batch in svc.batched(ids):
        db.execute(update(Node).where(Node.id.in_(batch), Node.trashed_at.is_(None)).values(trashed_at=stamp))
    db.commit()
    db.refresh(node)
    return node


@router.get("/trash", response_model=list[NodeOut])
def list_trash(
    limit: int = Query(200, ge=1, le=500),
    user: User = Depends(current_user), db: Session = Depends(get_db),
):
    parent = aliased(Node)
    q = (
        select(Node)
        .outerjoin(parent, Node.parent_id == parent.id)
        .where(
            Node.owner_id == user.id,
            Node.trashed_at.is_not(None),
            or_(Node.parent_id.is_(None), parent.trashed_at.is_(None), parent.trashed_at != Node.trashed_at),
        )
        .order_by(Node.trashed_at.desc(), Node.id)
        .limit(limit)
    )
    return db.scalars(q).all()

@router.post("/nodes/{node_id}/restore", response_model=NodeOut)
def restore_node(node_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    node = svc.get_node(db, user.id, node_id, trashed=True)
    stamp = node.trashed_at

    if node.parent_id is not None:
        parent = db.scalar(select(Node).where(Node.id == node.parent_id, Node.owner_id == user.id))
        if parent is None or parent.trashed_at is not None:
            node.parent_id = None
    node.name = svc.unique_name(db, user.id, node.parent_id, node.name)
    node.sort_key = svc.make_sort_key(node.name, node.kind)

    ids = [node.id] + [
        d.id for d in svc.descendants(db, user.id, node.id) if d.trashed_at == stamp
    ]
    for batch in svc.batched(ids):
        db.execute(update(Node).where(Node.id.in_(batch)).values(trashed_at=None))
    db.commit()
    db.refresh(node)
    return node

def _delete_blobs(blob, blob_ids: list[int]) -> None:
    for blob_id in blob_ids:
        blob.delete(blob_id)

@router.delete("/nodes/{node_id}")
def purge_node(
    node_id: int, background: BackgroundTasks,
    user: User = Depends(current_user), db: Session = Depends(get_db), blob=Depends(get_blob),
):
    node = svc.get_node(db, user.id, node_id, trashed=True)
    nodes = [node] + svc.descendants(db, user.id, node.id)
    blob_ids = svc.purge(db, nodes)
    db.commit()
    background.add_task(_delete_blobs, blob, blob_ids)
    return {"deleted": len(nodes)}

@router.delete("/trash")
def empty_trash(
    background: BackgroundTasks,
    user: User = Depends(current_user), db: Session = Depends(get_db), blob=Depends(get_blob),
):
    nodes = db.scalars(select(Node).where(Node.owner_id == user.id, Node.trashed_at.is_not(None))).all()
    blob_ids = svc.purge(db, list(nodes))
    db.commit()
    background.add_task(_delete_blobs, blob, blob_ids)
    return {"deleted": len(nodes)}
