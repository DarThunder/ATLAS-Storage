import os
import re
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="atlas-test-")
os.environ["ATLAS_DB_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["ATLAS_ADMIN_USER"] = "admin"
os.environ["ATLAS_ADMIN_PASSWORD"] = "secret"
os.environ["ATLAS_TMP_DIR"] = _tmp

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient

from app.blob import get_blob
from app.blob.blobstore import BlobError
from app.db import Base, engine
from app.main import app


class FakeResp:
    def __init__(self, status_code, headers, body):
        self.status_code, self.headers, self._body = status_code, headers, body

    def iter_bytes(self, _n=None):
        yield self._body

    def close(self):
        pass


class FakeBlob:

    def __init__(self):
        self.files: dict[int, bytes] = {}
        self.deleted: list[int] = []
        self._next = 1

    def upload_file(self, path, filename=None):
        fid = self._next
        self._next += 1
        self.files[fid] = Path(path).read_bytes()
        return fid

    def open(self, file_id, range_header=None):
        if file_id not in self.files:
            raise BlobError("404", status_code=404)
        data = self.files[file_id]
        total = len(data)
        m = re.match(r"bytes=(\d+)-(\d*)$", range_header or "")
        if not m:
            return FakeResp(200, {"content-length": str(total), "accept-ranges": "bytes"}, data)
        start = int(m.group(1))
        end = min(int(m.group(2)), total - 1) if m.group(2) else total - 1
        if start >= total:
            raise BlobError("416", status_code=416, headers={"content-range": f"bytes */{total}"})
        part = data[start : end + 1]
        return FakeResp(206, {
            "content-length": str(len(part)),
            "content-range": f"bytes {start}-{end}/{total}",
        }, part)

    def delete(self, file_id):
        self.deleted.append(file_id)
        self.files.pop(file_id, None)


@pytest.fixture()
def blob():
    fake = FakeBlob()
    app.dependency_overrides[get_blob] = lambda: fake
    yield fake
    app.dependency_overrides.clear()


@pytest.fixture()
def client(blob):
    Base.metadata.drop_all(engine)
    with TestClient(app) as c:
        c.headers["X-Atlas"] = "1"
        yield c


@pytest.fixture()
def auth(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "secret"})
    assert r.status_code == 200, r.text
    return client
