"use strict";

const $ = (id) => document.getElementById(id);

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (v == null || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children) if (c != null) node.append(c);
  return node;
}

function fmtSize(n) {
  if (!n) return "—";
  const u = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (n >= 1024 && i < u.length - 1) {
    n /= 1024;
    i++;
  }
  return `${n >= 10 || i === 0 ? Math.round(n) : n.toFixed(1)} ${u[i]}`;
}

function fmtDate(iso) {
  return iso
    ? new Date(iso).toLocaleString("es-MX", {
        dateStyle: "medium",
        timeStyle: "short",
      })
    : "";
}

let toastTimer;
function toast(msg) {
  const t = $("toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), 4000);
}

function iconFor(n) {
  if (n.kind === "folder") return "📁";
  const m = n.mimetype || "";
  if (m.startsWith("image/")) return "🖼️";
  if (m.startsWith("video/")) return "🎬";
  if (m.startsWith("audio/")) return "🎵";
  if (m === "application/pdf") return "📕";
  return "📄";
}

function previewKind(mime) {
  mime = (mime || "").toLowerCase();
  if (mime === "image/svg+xml") return null;
  if (mime.startsWith("image/")) return "image";
  if (mime.startsWith("video/")) return "video";
  if (mime.startsWith("audio/")) return "audio";
  if (mime === "application/pdf") return "pdf";
  return null;
}

const contentUrl = (id, dl = false) =>
  `/api/files/${id}/content${dl ? "?download=true" : ""}`;

async function api(path, { method = "GET", body } = {}) {
  const opts = {
    method,
    credentials: "same-origin",
    headers: { "X-Atlas": "1" },
  };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch("/api" + path, opts);
  if (res.status === 401 && path !== "/auth/login") {
    showLogin();
    throw new Error("Sesión expirada");
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail =
        typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {
      /* We are Charlie Kirk, we carry the flame🗣️🔥🔥🔥🔥 */
    }
    throw new Error(detail);
  }
  return res.status === 204 ? null : res.json();
}

const state = { view: "files", parent: null, cursor: null, loadToken: 0 };

function showLogin() {
  $("app-view").hidden = true;
  $("login-view").hidden = false;
}

function showApp(user) {
  $("login-view").hidden = true;
  $("app-view").hidden = false;
  $("whoami").textContent = user.username;
  route();
}

$("login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  $("login-error").textContent = "";
  try {
    const user = await api("/auth/login", {
      method: "POST",
      body: { username: f.get("username"), password: f.get("password") },
    });
    e.target.reset();
    showApp(user);
  } catch (err) {
    $("login-error").textContent = err.message;
  }
});

$("tab-login").addEventListener("click", () => {
  $("login-form").hidden = false;
  $("register-form").hidden = true;
  $("tab-login").classList.add("active");
  $("tab-register").classList.remove("active");
  $("tab-login").classList.remove("ghost");
  $("tab-register").classList.add("ghost");
});

$("tab-register").addEventListener("click", () => {
  $("login-form").hidden = true;
  $("register-form").hidden = false;
  $("tab-register").classList.add("active");
  $("tab-login").classList.remove("active");
  $("tab-register").classList.remove("ghost");
  $("tab-login").classList.add("ghost");
});

$("register-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  $("register-error").textContent = "";
  try {
    await api("/auth/register", {
      method: "POST",
      body: { username: f.get("username"), password: f.get("password") },
    });

    toast("Cuenta creada con éxito. Iniciando sesión...");
    const user = await api("/auth/login", {
      method: "POST",
      body: { username: f.get("username"), password: f.get("password") },
    });
    e.target.reset();
    showApp(user);
  } catch (err) {
    $("register-error").textContent = err.message;
  }
});

$("logout").addEventListener("click", async () => {
  try {
    await api("/auth/logout", { method: "POST" });
  } catch {
    /* We'll fight for the Gospel, we'll honor his name */
  }
  showLogin();
});

function route() {
  const h = location.hash.replace(/^#/, "") || "/";
  const m = h.match(/^\/folder\/(\d+)$/);
  state.view = h === "/trash" ? "trash" : "files";
  state.parent = m ? Number(m[1]) : null;
  $("nav-files").classList.toggle("active", state.view === "files");
  $("nav-trash").classList.toggle("active", state.view === "trash");
  $("files-actions").hidden = state.view !== "files";
  $("trash-actions").hidden = state.view !== "trash";
  load(true);
}
window.addEventListener("hashchange", () => {
  if (!$("app-view").hidden) route();
});

async function load(reset) {
  const token = ++state.loadToken;
  if (reset) {
    state.cursor = null;
    $("list").replaceChildren();
    $("empty").hidden = true;
    $("load-more").hidden = true;
    renderCrumbs();
  }
  try {
    let items,
      next = null;
    if (state.view === "trash") {
      items = await api("/trash");
    } else {
      const q = new URLSearchParams({ limit: "100" });
      if (state.parent != null) q.set("parent_id", state.parent);
      if (state.cursor) q.set("cursor", state.cursor);
      ({ items, next_cursor: next } = await api("/nodes?" + q));
    }
    if (token !== state.loadToken) return;
    state.cursor = next;
    for (const n of items) $("list").append(renderRow(n));
    $("load-more").hidden = !next;
    if (reset && !items.length) {
      $("empty").textContent =
        state.view === "trash"
          ? "La papelera está vacía."
          : "Esta carpeta está vacía. Arrastra archivos aquí o usa “Subir archivos”.";
      $("empty").hidden = false;
    }
  } catch (err) {
    if (token === state.loadToken) toast(err.message);
  }
}

$("load-more").addEventListener("click", () => load(false));

async function renderCrumbs() {
  const box = $("crumbs");
  const token = state.loadToken;
  if (state.view === "trash") {
    box.replaceChildren(el("span", { class: "crumb", text: "Papelera" }));
    return;
  }
  const crumb = (id, name) => {
    const c = el("a", {
      class: "crumb",
      href: id == null ? "#/" : `#/folder/${id}`,
      text: name,
    });
    wireDropTarget(c, id);
    return c;
  };
  const render = (path) => {
    const parts = [crumb(null, "Mis archivos")];
    for (const p of path)
      parts.push(el("span", { class: "sep", text: "›" }), crumb(p.id, p.name));
    box.replaceChildren(...parts);
  };
  render([]);
  if (state.parent != null) {
    try {
      const path = await api(`/nodes/${state.parent}/path`);
      if (token === state.loadToken) render(path);
    } catch (err) {
      if (token === state.loadToken) {
        toast(err.message);
        location.hash = "#/";
      }
    }
  }
}

function renderRow(n) {
  const inTrash = state.view === "trash";
  const name = el("span", { class: "name", text: n.name, title: n.name });
  const actions = el("span", { class: "actions" });
  const row = el(
    "div",
    { class: "row", role: "listitem", "data-id": n.id },
    el("span", { class: "icon", text: iconFor(n) }),
    name,
    el("span", {
      class: "meta",
      text: n.kind === "folder" ? "" : fmtSize(n.size),
    }),
    el("span", {
      class: "meta",
      text: fmtDate(inTrash ? n.trashed_at : n.updated_at),
    }),
    actions,
  );

  const btn = (label, fn, cls) =>
    actions.append(
      el("button", { class: cls || "ghost", text: label, onclick: fn }),
    );

  if (inTrash) {
    btn("Restaurar", () =>
      act(
        () => api(`/nodes/${n.id}/restore`, { method: "POST" }),
        row,
        "Restaurado",
      ),
    );
    btn(
      "Eliminar",
      () => {
        if (
          confirm(
            `¿Eliminar “${n.name}” definitivamente? No se puede deshacer.`,
          )
        )
          act(() => api(`/nodes/${n.id}`, { method: "DELETE" }), row);
      },
      "ghost danger",
    );
    return row;
  }

  name.addEventListener("click", () => open(n));
  if (n.kind === "file")
    btn("Descargar", () => {
      location.href = contentUrl(n.id, true);
    });
  btn("Renombrar", async () => {
    const next = prompt("Nuevo nombre:", n.name);
    if (!next || next === n.name) return;
    try {
      await api(`/nodes/${n.id}`, { method: "PATCH", body: { name: next } });
      load(true);
    } catch (err) {
      toast(err.message);
    }
  });
  btn(
    "Papelera",
    () =>
      act(
        () => api(`/nodes/${n.id}/trash`, { method: "POST" }),
        row,
        "Movido a la papelera",
      ),
    "ghost danger",
  );

  row.draggable = true;
  row.addEventListener("dragstart", (e) => {
    e.dataTransfer.setData("application/x-atlas-node", String(n.id));
    e.dataTransfer.effectAllowed = "move";
    row.classList.add("dragging");
  });
  row.addEventListener("dragend", () => row.classList.remove("dragging"));
  if (n.kind === "folder") wireDropTarget(row, n.id);
  return row;
}

async function act(fn, row, okMsg) {
  try {
    await fn();
    row.remove();
    if (!$("list").children.length) load(true);
    if (okMsg) toast(okMsg);
  } catch (err) {
    toast(err.message);
  }
}

function open(n) {
  if (n.kind === "folder") {
    location.hash = `#/folder/${n.id}`;
    return;
  }
  const kind = previewKind(n.mimetype);
  if (!kind) {
    location.href = contentUrl(n.id, true);
    return;
  }

  const src = contentUrl(n.id);
  const body = $("preview-body");
  let node;
  if (kind === "image") node = el("img", { src, alt: n.name });
  else if (kind === "video")
    node = el("video", { src, controls: true, autoplay: true });
  else if (kind === "audio")
    node = el("audio", { src, controls: true, autoplay: true });
  else node = el("iframe", { src, title: n.name });
  body.replaceChildren(node);
  $("preview-title").textContent = n.name;
  $("preview-download").href = contentUrl(n.id, true);
  $("preview").showModal();
}

function closePreview() {
  $("preview").close();
  $("preview-body").replaceChildren();
}
$("preview-close").addEventListener("click", closePreview);
$("preview").addEventListener("close", () =>
  $("preview-body").replaceChildren(),
);
$("preview").addEventListener("click", (e) => {
  if (e.target === $("preview")) closePreview();
});

function wireDropTarget(elm, folderId) {
  const isNodeDrag = (e) =>
    e.dataTransfer.types.includes("application/x-atlas-node");
  elm.addEventListener("dragover", (e) => {
    if (!isNodeDrag(e)) return;
    e.preventDefault();
    e.stopPropagation();
    elm.classList.add("drop-target");
  });
  elm.addEventListener("dragleave", () => elm.classList.remove("drop-target"));
  elm.addEventListener("drop", async (e) => {
    elm.classList.remove("drop-target");
    if (!isNodeDrag(e)) return;
    e.preventDefault();
    e.stopPropagation();
    const id = Number(e.dataTransfer.getData("application/x-atlas-node"));
    if (!id || id === folderId) return;
    try {
      await api(`/nodes/${id}`, {
        method: "PATCH",
        body: { parent_id: folderId },
      });
      toast("Movido");
      load(true);
    } catch (err) {
      toast(err.message);
    }
  });
}

$("new-folder").addEventListener("click", async () => {
  const name = prompt("Nombre de la carpeta:");
  if (!name) return;
  try {
    await api("/folders", {
      method: "POST",
      body: { name, parent_id: state.parent },
    });
    load(true);
  } catch (err) {
    toast(err.message);
  }
});

$("empty-trash").addEventListener("click", async () => {
  if (!confirm("¿Vaciar la papelera? Se eliminará todo definitivamente."))
    return;
  try {
    await api("/trash", { method: "DELETE" });
    load(true);
  } catch (err) {
    toast(err.message);
  }
});

const queue = [];
let uploading = false;

function enqueue(files) {
  if (state.view !== "files") return;
  for (const file of files) {
    const bar = el("progress", { max: 100, value: 0 });
    const stateEl = el("span", { class: "up-state muted", text: "En cola" });
    const item = el(
      "div",
      { class: "up" },
      el("div", { class: "up-name", text: file.name, title: file.name }),
      stateEl,
      bar,
    );
    $("uploads-list").append(item);
    queue.push({ file, parent: state.parent, item, bar, stateEl });
  }
  $("uploads").hidden = false;
  pump();
}

async function pump() {
  if (uploading) return;
  uploading = true;
  while (queue.length) await uploadOne(queue.shift());
  uploading = false;
}

function uploadOne(job) {
  return new Promise((resolve) => {
    const xhr = new XMLHttpRequest();
    const q = job.parent != null ? `?parent_id=${job.parent}` : "";
    xhr.open("POST", "/api/files" + q);
    xhr.setRequestHeader("X-Atlas", "1");
    xhr.upload.onprogress = (e) => {
      if (!e.lengthComputable) return;
      job.bar.value = (e.loaded / e.total) * 100;
      job.stateEl.textContent =
        e.loaded >= e.total
          ? "Procesando…"
          : `${Math.round((e.loaded / e.total) * 100)}%`;
    };
    const fail = (msg) => {
      job.item.classList.add("err");
      job.stateEl.textContent = msg;
      resolve();
    };
    xhr.onerror = () => fail("Error de red");
    xhr.onload = () => {
      if (xhr.status === 401) {
        showLogin();
        return fail("Sesión expirada");
      }
      if (xhr.status >= 300) {
        let msg = `Error ${xhr.status}`;
        try {
          const d = JSON.parse(xhr.responseText).detail;
          if (typeof d === "string") msg = d;
        } catch {
          /* We are Charlie Kirk, his courage our own */
        }
        return fail(msg);
      }
      job.bar.value = 100;
      job.stateEl.textContent = "Listo";
      if (state.view === "files" && state.parent === job.parent) load(true);
      resolve();
    };
    const fd = new FormData();
    fd.append("file", job.file, job.file.name);
    xhr.send(fd);
  });
}

$("upload-btn").addEventListener("click", () => $("file-input").click());
$("file-input").addEventListener("change", (e) => {
  enqueue([...e.target.files]);
  e.target.value = "";
});
$("uploads-clear").addEventListener("click", () => {
  for (const c of [...$("uploads-list").children]) {
    const s = c.querySelector(".up-state").textContent;
    if (s === "Listo" || c.classList.contains("err")) c.remove();
  }
  if (!$("uploads-list").children.length) $("uploads").hidden = true;
});

let dragDepth = 0;
const isFileDrag = (e) =>
  e.dataTransfer && [...e.dataTransfer.types].includes("Files");
const dz = $("dropzone");
dz.addEventListener("dragenter", (e) => {
  if (isFileDrag(e) && state.view === "files") {
    dragDepth++;
    $("drop-hint").hidden = false;
  }
});
dz.addEventListener("dragleave", (e) => {
  if (isFileDrag(e) && --dragDepth <= 0) {
    dragDepth = 0;
    $("drop-hint").hidden = true;
  }
});
dz.addEventListener("dragover", (e) => {
  if (isFileDrag(e)) e.preventDefault();
});
dz.addEventListener("drop", (e) => {
  if (!isFileDrag(e)) return;
  e.preventDefault();
  dragDepth = 0;
  $("drop-hint").hidden = true;
  enqueue([...e.dataTransfer.files]);
});

(async () => {
  try {
    showApp(await api("/auth/me"));
  } catch {
    showLogin();
  }
})();
