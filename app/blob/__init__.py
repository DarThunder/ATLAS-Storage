# ATLAS — Personal cloud drive server
# Copyright (C) 2026-Present  DarThunder
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Acceso al holder. Se crea de forma perezosa y se inyecta con Depends(get_blob),
así las pruebas pueden sustituirlo por un doble."""

_client = None


def get_blob():
    global _client
    if _client is None:
        from .blobstore import BlobClient

        _client = BlobClient()
    return _client


def close_blob() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None
