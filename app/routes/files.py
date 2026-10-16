# ATLAS — Personal cloud drive server
# Copyright (C) 2026-Present  DarThunder
# SPDX-License-Identifier: AGPL-3.0-or-later

import logging
import re
import tempfile
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

import config
import services as svc
from blob import get_blob
from blob.blobstore import BlobError, mime_for_name, stream_body
from db import Node, User, get_db
from schemas import NodeOut
from security import current_user

log = logging.getLogger("atlas.files")
router = APIRouter(tags=["files"])

COPY_BLOCK = 1024 * 1024

@router.post("/files", response_model=NodeOut, status_code=201)
def upload_file(
    request: Request,
    parent_id: int | None = None,
    file: UploadFile = File(...),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    blob=Depends(get_blob),
):
    svc.require_folder(db, user.id, parent_id)

    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > config.MAX_UPLOAD_BYTES + 1024 * 1024:
        raise HTTPException(413, "Archivo demasiado grande")

    name = svc.clean_upload_name(file.filename)
    suffix = re.sub(r"[^A-Za-z0-9.]", "", Path(name).suffix)[:16]

    with tempfile.NamedTemporaryFile(dir=config.TMP_DIR, suffix=suffix) as tmp:
        size = 0
        while block := file.file.read(COPY_BLOCK):
            size += len(block)
            if size > config.MAX_UPLOAD_BYTES:
                raise HTTPException(413, "Archivo demasiado grande")
            tmp.write(block)
        tmp.flush()
        try:
            blob_id = blob.upload_file(Path(tmp.name), name)
        except BlobError:
            log.exception("Falló la subida al holder")
            raise HTTPException(502, "No se pudo guardar en el almacenamiento")

    try:
        final_name = svc.unique_name(db, user.id, parent_id, name)
        node = Node(
            owner_id=user.id, parent_id=parent_id, kind="file", name=final_name,
            sort_key=svc.make_sort_key(final_name, "file"),
            blob_id=blob_id, size=size, mimetype=mime_for_name(name),
        )
        db.add(node)
        db.commit()
    except BaseException:
        db.rollback()
        blob.delete(blob_id)
        raise
    return node

@router.get("/files/{node_id}/content")
def file_content(
    node_id: int,
    request: Request,
    download: bool = False,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    blob=Depends(get_blob),
):
    node = svc.get_node(db, user.id, node_id)
    if node.kind != "file" or node.blob_id is None:
        raise HTTPException(400, "No es un archivo")

    try:
        resp = blob.open(node.blob_id, request.headers.get("Range"))
    except BlobError as e:
        if e.status_code == 416:
            return Response(
                status_code=416,
                headers={"Content-Range": e.headers.get("content-range", f"bytes */{node.size}")},
            )
        if e.status_code == 404:
            raise HTTPException(404, "El contenido no existe en el almacenamiento")
        log.error("Holder falló al abrir blob %s: %s", node.blob_id, e)
        raise HTTPException(502, "Error con el almacenamiento")

    inline = svc.can_inline(node.mimetype) and not download
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Disposition": f"{'inline' if inline else 'attachment'}; filename*=UTF-8''{quote(node.name)}",
        "X-Content-Type-Options": "nosniff",
    }
    if node.mimetype != "application/pdf":
        headers["Content-Security-Policy"] = "default-src 'none'; sandbox"
    for h in ("Content-Length", "Content-Range"):
        if h.lower() in resp.headers:
            headers[h] = resp.headers[h.lower()]

    return StreamingResponse(
        stream_body(resp),
        status_code=resp.status_code,
        media_type=node.mimetype if inline else "application/octet-stream",
        headers=headers,
    )
