# ATLAS — Personal cloud drive server
# Copyright (C) 2026-Present  DarThunder
# SPDX-License-Identifier: AGPL-3.0-or-later

import os


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


HOLDER_URL = os.getenv("HOLDER_URL", "http://localhost:8080")
HOLDER_API_TOKEN = os.getenv("HOLDER_API_TOKEN") or None

DB_URL = os.getenv("ATLAS_DB_URL", "sqlite:///./atlas.db")

ADMIN_USER = os.getenv("ATLAS_ADMIN_USER", "admin")
ADMIN_PASSWORD = os.getenv("ATLAS_ADMIN_PASSWORD") or None

SESSION_TTL_DAYS = int(os.getenv("ATLAS_SESSION_TTL_DAYS", "30"))
COOKIE_SECURE = _bool("ATLAS_COOKIE_SECURE", False)

MAX_UPLOAD_BYTES = int(os.getenv("ATLAS_MAX_UPLOAD_MB", "2048")) * 1024 * 1024
TMP_DIR = os.getenv("ATLAS_TMP_DIR") or None
