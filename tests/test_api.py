from app.db import SessionLocal, User
from app.security import hash_password

def mkdir(c, name, parent=None):
    r = c.post("/api/folders", json={"name": name, "parent_id": parent})
    assert r.status_code == 201, r.text
    return r.json()

def upload(c, name, data=b"hola", parent=None):
    params = {"parent_id": parent} if parent is not None else {}
    r = c.post("/api/files", params=params, files={"file": (name, data)})
    assert r.status_code == 201, r.text
    return r.json()

def names(c, parent=None):
    params = {"parent_id": parent} if parent is not None else {}
    return [n["name"] for n in c.get("/api/nodes", params=params).json()["items"]]

def test_requires_login(client):
    assert client.get("/api/nodes").status_code == 401
    assert client.post("/api/auth/login", json={"username": "admin", "password": "mal"}).status_code == 401

def test_login_me_logout(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "secret"})
    assert r.status_code == 200
    assert "httponly" in r.headers["set-cookie"].lower()
    assert client.get("/api/auth/me").json()["username"] == "admin"
    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").status_code == 401

def test_csrf_header_required(auth):
    del auth.headers["X-Atlas"]
    assert auth.post("/api/folders", json={"name": "x"}).status_code == 403

def test_folders_and_ordering(auth):
    mkdir(auth, "zeta")
    upload(auth, "a.txt")
    mkdir(auth, "Alfa")
    assert names(auth) == ["Alfa", "zeta", "a.txt"]

def test_duplicate_folder_name_conflicts(auth):
    mkdir(auth, "docs")
    assert auth.post("/api/folders", json={"name": "DOCS"}).status_code == 409

def test_invalid_names(auth):
    assert auth.post("/api/folders", json={"name": ".."}).status_code == 400
    assert auth.post("/api/folders", json={"name": "   "}).status_code == 400

def test_breadcrumbs(auth):
    a = mkdir(auth, "a")
    b = mkdir(auth, "b", a["id"])
    path = auth.get(f"/api/nodes/{b['id']}/path").json()
    assert [p["name"] for p in path] == ["a", "b"]

def test_pagination(auth):
    for i in range(5):
        mkdir(auth, f"f{i}")
    seen, cursor = [], None
    while True:
        params = {"limit": 2, **({"cursor": cursor} if cursor else {})}
        page = auth.get("/api/nodes", params=params).json()
        seen += [n["name"] for n in page["items"]]
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert seen == [f"f{i}" for i in range(5)]
    assert auth.get("/api/nodes", params={"cursor": "basura"}).status_code == 400

def test_upload_and_download(auth, blob):
    f = upload(auth, "foto.png", b"0123456789")
    assert f["size"] == 10 and f["mimetype"] == "image/png"
    r = auth.get(f"/api/files/{f['id']}/content")
    assert r.status_code == 200 and r.content == b"0123456789"
    assert r.headers["content-disposition"].startswith("inline")
    assert r.headers["x-content-type-options"] == "nosniff"

def test_range_request(auth):
    f = upload(auth, "video.mp4", b"0123456789")
    r = auth.get(f"/api/files/{f['id']}/content", headers={"Range": "bytes=2-5"})
    assert r.status_code == 206
    assert r.content == b"2345"
    assert r.headers["content-range"] == "bytes 2-5/10"
    r = auth.get(f"/api/files/{f['id']}/content", headers={"Range": "bytes=99-"})
    assert r.status_code == 416

def test_unsafe_types_download_as_attachment(auth):
    f = upload(auth, "pagina.html", b"<script>alert(1)</script>")
    r = auth.get(f"/api/files/{f['id']}/content")
    assert r.headers["content-disposition"].startswith("attachment")
    assert r.headers["content-type"].startswith("application/octet-stream")
    svg = upload(auth, "dibujo.svg", b"<svg/>")
    assert auth.get(f"/api/files/{svg['id']}/content").headers["content-disposition"].startswith("attachment")

def test_force_download(auth):
    f = upload(auth, "foto.png", b"x")
    r = auth.get(f"/api/files/{f['id']}/content", params={"download": "true"})
    assert r.headers["content-disposition"].startswith("attachment")

def test_upload_name_collision_renames(auth):
    upload(auth, "a.txt")
    second = upload(auth, "a.txt")
    assert second["name"] == "a (1).txt"
    assert upload(auth, "a.txt")["name"] == "a (2).txt"

def test_upload_sanitizes_filename(auth):
    f = upload(auth, "../../etc/passwd")
    assert f["name"] == "passwd"

def test_empty_file(auth):
    f = upload(auth, "vacio.txt", b"")
    assert f["size"] == 0

def test_move_and_rename(auth):
    a = mkdir(auth, "a")
    f = upload(auth, "x.txt")
    r = auth.patch(f"/api/nodes/{f['id']}", json={"parent_id": a["id"]})
    assert r.status_code == 200 and names(auth, a["id"]) == ["x.txt"]
    r = auth.patch(f"/api/nodes/{f['id']}", json={"name": "y.txt"})
    assert r.json()["name"] == "y.txt" and r.json()["parent_id"] == a["id"]
    r = auth.patch(f"/api/nodes/{f['id']}", json={"parent_id": None})  # null explícito = raíz
    assert r.json()["parent_id"] is None

def test_cannot_move_folder_into_itself(auth):
    a = mkdir(auth, "a")
    b = mkdir(auth, "b", a["id"])
    assert auth.patch(f"/api/nodes/{a['id']}", json={"parent_id": a["id"]}).status_code == 400
    assert auth.patch(f"/api/nodes/{a['id']}", json={"parent_id": b["id"]}).status_code == 400

def test_move_conflict(auth):
    a = mkdir(auth, "a")
    upload(auth, "x.txt", parent=a["id"])
    f = upload(auth, "x.txt")
    assert auth.patch(f"/api/nodes/{f['id']}", json={"parent_id": a["id"]}).status_code == 409

def test_trash_restore_folder_with_contents(auth):
    a = mkdir(auth, "a")
    f = upload(auth, "x.txt", parent=a["id"])
    assert auth.post(f"/api/nodes/{a['id']}/trash").status_code == 200

    assert names(auth) == []
    assert auth.get(f"/api/files/{f['id']}/content").status_code == 404
    assert [n["name"] for n in auth.get("/api/trash").json()] == ["a"]

    assert auth.post(f"/api/nodes/{a['id']}/restore").status_code == 200
    assert names(auth) == ["a"] and names(auth, a["id"]) == ["x.txt"]
    assert auth.get("/api/trash").json() == []

def test_restore_renames_on_conflict(auth):
    f = upload(auth, "x.txt")
    auth.post(f"/api/nodes/{f['id']}/trash")
    upload(auth, "x.txt")
    r = auth.post(f"/api/nodes/{f['id']}/restore")
    assert r.json()["name"] == "x (1).txt"

def test_restore_goes_to_root_if_parent_trashed(auth):
    a = mkdir(auth, "a")
    f = upload(auth, "x.txt", parent=a["id"])
    auth.post(f"/api/nodes/{f['id']}/trash")
    auth.post(f"/api/nodes/{a['id']}/trash")
    r = auth.post(f"/api/nodes/{f['id']}/restore")
    assert r.status_code == 200 and r.json()["parent_id"] is None

def test_purge_requires_trash_and_deletes_blobs(auth, blob):
    a = mkdir(auth, "a")
    f1 = upload(auth, "1.txt", parent=a["id"])
    upload(auth, "2.txt", parent=a["id"])
    assert auth.delete(f"/api/nodes/{a['id']}").status_code == 404

    auth.post(f"/api/nodes/{a['id']}/trash")
    assert auth.delete(f"/api/nodes/{a['id']}").json() == {"deleted": 3}
    assert sorted(blob.deleted) == [1, 2]
    assert auth.get(f"/api/nodes/{f1['id']}").status_code == 404

def test_empty_trash(auth, blob):
    f = upload(auth, "x.txt")
    keep = upload(auth, "keep.txt")
    auth.post(f"/api/nodes/{f['id']}/trash")
    assert auth.delete("/api/trash").json() == {"deleted": 1}
    assert blob.deleted == [1] and 2 in blob.files
    assert names(auth) == [keep["name"]]

def test_users_are_isolated(auth, client):
    f = upload(auth, "secreto.txt")
    with SessionLocal() as db:
        db.add(User(username="otra", password_hash=hash_password("pw")))
        db.commit()

    client.post("/api/auth/logout")
    assert client.post("/api/auth/login", json={"username": "otra", "password": "pw"}).status_code == 200
    assert names(client) == []
    assert client.get(f"/api/nodes/{f['id']}").status_code == 404
    assert client.get(f"/api/files/{f['id']}/content").status_code == 404
    assert client.patch(f"/api/nodes/{f['id']}", json={"name": "x"}).status_code == 404
    assert client.post(f"/api/nodes/{f['id']}/trash").status_code == 404

def test_static_ui_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "ATLAS" in r.text
    assert "default-src 'self'" in r.headers["content-security-policy"]
