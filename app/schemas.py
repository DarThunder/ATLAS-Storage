# ATLAS — Personal cloud drive server
# Copyright (C) 2026-Present  DarThunder
# SPDX-License-Identifier: AGPL-3.0-or-later

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

UtcDT = Annotated[datetime, PlainSerializer(lambda d: d.isoformat() + "Z", return_type=str)]


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str


class FolderIn(BaseModel):
    name: str
    parent_id: int | None = None


class NodeUpdate(BaseModel):
    name: str | None = None
    parent_id: int | None = None


class NodeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    parent_id: int | None
    kind: str
    name: str
    size: int
    mimetype: str | None
    created_at: UtcDT
    updated_at: UtcDT
    trashed_at: UtcDT | None


class PageOut(BaseModel):
    items: list[NodeOut]
    next_cursor: str | None


class CrumbOut(BaseModel):
    id: int
    name: str
