# ATLAS

**A**dvanced **T**echnology for **L**inked **A**rchival **S**ystems — a personal "Drive" on top of the blob holder.

```
Browser ──cookie──▶ ATLAS (FastAPI) ──X-API-Key──▶ holder
                      └─ SQLite: users, sessions, nodes     (deduplicated chunks)
```

The holder remains a "dumb" blob store. ATLAS adds folders, users, trash, and the web interface.

## Startup

```bash
cd atlas
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env          # edit HOLDER_URL, HOLDER_API_TOKEN and ATLAS_ADMIN_PASSWORD
set -a && source .env && set +a
uvicorn app.main:app --port 8082
```

Open <http://localhost:8082>. If you don't set `ATLAS_ADMIN_PASSWORD`, one is generated and printed in the log on first startup.
Behind HTTPS, set `ATLAS_COOKIE_SECURE=true`.

Tests (they use a mock holder, the real one isn't needed):

```bash
pytest
```

## API (`/api`)

| Method | Route                                       | What it does                                             |
| ------ | ------------------------------------------- | -------------------------------------------------------- |
| POST   | `/auth/register`                            | New user registration                                    |
| POST   | `/auth/login` · `/auth/logout`              | HttpOnly cookie session                                  |
| GET    | `/auth/me`                                  | Current user                                             |
| GET    | `/nodes?parent_id=&cursor=&limit=`          | List a folder (folders first, cursor pagination)         |
| GET    | `/nodes/{id}` · `/nodes/{id}/path`          | Detail · breadcrumbs                                     |
| POST   | `/folders`                                  | Create folder `{name, parent_id}`                        |
| POST   | `/files?parent_id=`                         | Upload file (multipart, field `file`)                    |
| GET    | `/files/{id}/content[?download=true]`       | Content, with `Range` support                            |
| PATCH  | `/nodes/{id}`                               | Rename (`name`) and/or move (`parent_id`, `null` = root) |
| POST   | `/nodes/{id}/trash` · `/nodes/{id}/restore` | Trash                                                    |
| GET    | `/trash`                                    | Items sent directly to trash                             |
| DELETE | `/nodes/{id}` · `/trash`                    | Permanent deletion (only from trash)                     |

Requests that modify data must carry the `X-Atlas: 1` header (CSRF defense; the frontend already sends it).

## Structure

```
app/
  main.py        FastAPI + static frontend + security headers
  config.py      environment variables
  db.py          models: User, UserSession, Node
  security.py    scrypt, sessions, CSRF, initial user
  services.py    tree rules (names, cycles, descendants, trash)
  routes/        auth.py · nodes.py · files.py
  blob/          blobstore.py + chunking.py copied from OmniCast
web/             index.html · app.js · style.css (vanilla JS, no build)
tests/
```

## Decisions that leave the door open

- **`owner_id` on everything** and all queries scoped to the owner: moving to multiuser is just adding registration and quotas.
- **The API knows nothing about the frontend.** Swapping `web/` for React/Svelte doesn't touch the backend.
- **Logical trash** (`trashed_at`): the actual blob is only deleted from the holder on permanent deletion.
- **`BlobClient` isolated in `app/blob/`**: when there are two copies to maintain, promote it to a shared package (`holder-client`) and replace this folder.
- **Each app only deletes the `file_id`s it created**, so it doesn't step on OmniCast references if they share a holder.

## Known MVP limitations

- **Two-hop upload**: browser → ATLAS (temp on disk) → holder. Later on, browser-side chunking (WASM) with `/chunks/check` to deduplicate before uploading.
- **No resumption** of interrupted uploads.
- **Best-effort deletion on the holder**: if the holder is down at that moment, the `FileRecord` is left orphaned there (GC only cleans up chunks). Future solution: an "outbox" table with retries.
- **In-memory login throttle**: only valid with a single worker.
- **No migrations**: `create_all` on startup. Add Alembic before the first schema change in production.
- **PDF**: served without `sandbox` in the CSP because the browser viewer doesn't work inside one; the rest of the previewable types do include it.

## Roadmap

Multi-select and batch move · search by name · thumbnails · shared links · per-user quotas · copy/duplicate (new `FileRecord` with the same chunks) · file versions.

## License

[AGPLv3](LICENSE) — if you run a modified version of ATLAS, you must make your source code available.
