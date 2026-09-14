import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const EXAMPLE = [
  "# one link per line — Civitai (civitai.com or civitai.red) or Hugging Face",
  "# folder|link sets the folder, e.g. diffusion_models|https://civitai.com/models/123?modelVersionId=456",
].join("\n");

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "style") Object.assign(node.style, v);
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  for (const c of children) node.append(c);
  return node;
}

const fieldStyle = {
  width: "100%", boxSizing: "border-box", padding: "6px 8px", borderRadius: "6px",
  border: "1px solid var(--border-color, #444)", background: "var(--comfy-input-bg, #222)",
  color: "var(--input-text, #ddd)", font: "inherit",
};
const buttonStyle = {
  padding: "6px 12px", borderRadius: "6px", border: "1px solid var(--border-color, #444)",
  background: "var(--comfy-menu-bg, #333)", color: "var(--fg-color, #eee)", cursor: "pointer",
};

function gb(bytes) {
  return bytes ? `${(bytes / 1e9).toFixed(2)} GB` : "";
}

function render(container) {
  const keyNote = el("div", { style: { fontSize: "12px", opacity: 0.75 } });
  const civitai = el("input", { type: "password", autocomplete: "off", style: fieldStyle });
  const hf = el("input", { type: "password", autocomplete: "off", style: fieldStyle });
  const list = el("textarea", { rows: 8, spellcheck: "false", placeholder: EXAMPLE,
    style: { ...fieldStyle, fontFamily: "monospace", fontSize: "12px", resize: "vertical" } });
  const message = el("div", { style: { fontSize: "12px", minHeight: "16px" } });
  const jobs = el("div", { style: { display: "flex", flexDirection: "column", gap: "6px" } });

  async function saveKeys() {
    const res = await api.fetchApi("/aiangel/keys", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ civitai: civitai.value, huggingface: hf.value }),
    });
    civitai.value = ""; hf.value = "";
    message.textContent = res.ok ? "Keys saved on this pod's volume." : "Could not save keys.";
    refresh();
  }

  async function download() {
    if (civitai.value || hf.value) await saveKeys();
    const res = await api.fetchApi("/aiangel/download", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: list.value }),
    });
    const data = await res.json();
    message.textContent = res.ok
      ? `${data.queued} file(s) queued. Press R in ComfyUI after they finish to refresh model lists.`
      : `Check the list: ${data.error}`;
    refresh();
  }

  async function refresh() {
    if (!container.isConnected) return;
    let data;
    try {
      data = await (await api.fetchApi("/aiangel/status")).json();
    } catch {
      return;
    }
    civitai.placeholder = data.keys.civitai ? `saved: ${data.keys.civitai}` : "Civitai API key";
    hf.placeholder = data.keys.huggingface ? `saved: ${data.keys.huggingface}` : "Hugging Face token (optional)";
    keyNote.textContent = `Files go to ${data.models_dir}`;
    jobs.replaceChildren(...data.jobs.slice().reverse().map((j) => {
      const pct = j.size && j.done_bytes ? Math.min(100, (100 * j.done_bytes) / j.size) : 0;
      const bar = el("div", { style: { height: "4px", borderRadius: "2px", background: "var(--border-color, #444)" } },
        el("div", { style: { height: "100%", width: `${j.state === "done" ? 100 : pct}%`, borderRadius: "2px",
          background: j.state === "failed" ? "#d9534f" : "#4caf50" } }));
      const title = j.name ? `${j.folder}/${j.name}` : j.url;
      const detail = j.state === "downloading"
        ? `${gb(j.done_bytes)} / ${gb(j.size)}`
        : (j.message || j.state);
      return el("div", { style: { fontSize: "12px", display: "flex", flexDirection: "column", gap: "2px" } },
        el("div", { style: { wordBreak: "break-all" } }, title),
        bar,
        el("div", { style: { opacity: 0.75 } }, `${j.state} · ${detail}`));
    }));
  }

  container.replaceChildren(el("div",
    { style: { display: "flex", flexDirection: "column", gap: "10px", padding: "12px" } },
    el("div", { style: { fontWeight: "600" } }, "Model list download"),
    el("div", { style: { fontSize: "12px", opacity: 0.8 } },
      "Paste a list of model links and download them all at once. Your keys stay on this pod."),
    civitai, hf,
    list,
    el("div", { style: { display: "flex", gap: "8px" } },
      el("button", { style: buttonStyle, onclick: download }, "Download all"),
      el("button", { style: buttonStyle, onclick: saveKeys }, "Save keys only")),
    message, keyNote, jobs));

  refresh();
  const timer = setInterval(() => (container.isConnected ? refresh() : clearInterval(timer)), 2000);
}

// ---------------------------------------------------------------- Outputs tab

const SEEN_KEY = "aiangel.outputs.downloadedUpTo";

function readMark() {
  try { return Number(localStorage.getItem(SEEN_KEY)) || 0; } catch { return 0; }
}

function writeMark(value) {
  try { localStorage.setItem(SEEN_KEY, String(value)); } catch { /* private window */ }
}

function size(bytes) {
  if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(2)} GB`;
  if (bytes >= 1e6) return `${(bytes / 1e6).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1e3))} KB`;
}

function viewUrl(path, preview) {
  const i = path.lastIndexOf("/");
  const q = new URLSearchParams({ filename: path.slice(i + 1), type: "output" });
  if (i > 0) q.set("subfolder", path.slice(0, i));
  if (preview) q.set("preview", "webp;60");
  return api.apiURL(`/view?${q}`);
}

// A form POST lets the browser stream the ZIP straight to disk, however large.
function downloadZip(paths) {
  const frame = "aiangel-zip-frame";
  if (!document.getElementById(frame)) {
    document.body.append(el("iframe", { id: frame, name: frame, style: { display: "none" } }));
  }
  const form = el("form", { method: "POST", action: api.apiURL("/aiangel/outputs/zip"), target: frame },
    el("input", { type: "hidden", name: "files", value: JSON.stringify(paths) }));
  document.body.append(form);
  form.submit();
  form.remove();
}

function renderOutputs(container) {
  let files = [];
  let filter = "all";
  let limit = 60;
  const selected = new Set();

  const primary = el("button", { style: { ...buttonStyle, width: "100%", padding: "10px 12px",
    fontWeight: "600", background: "#2e7d32", borderColor: "#2e7d32", color: "#fff" } });
  const selBtn = el("button", { style: buttonStyle });
  const allBtn = el("button", { style: buttonStyle });
  const clearBtn = el("button", { style: buttonStyle }, "Clear");
  const chips = el("div", { style: { display: "flex", gap: "6px", flexWrap: "wrap" } });
  const summary = el("div", { style: { fontSize: "12px", opacity: 0.75 } });
  const grid = el("div", { style: { display: "grid", gap: "6px",
    gridTemplateColumns: "repeat(auto-fill, minmax(96px, 1fr))" } });
  const more = el("button", { style: { ...buttonStyle, display: "none" } }, "Show more");
  const note = el("div", { style: { fontSize: "12px" } });
  note.hidden = true;
  const cmd = el("textarea", { rows: 3, readonly: "", spellcheck: "false",
    style: { ...fieldStyle, fontFamily: "monospace", fontSize: "11px", resize: "none" } });

  const visible = () => files.filter((f) => filter === "all" || f.kind === filter);
  const bytesOf = (list) => list.reduce((n, f) => n + f.size, 0);

  function start(list, advanceMark) {
    if (!list.length) return;
    downloadZip(list.map((f) => f.path));
    if (advanceMark) writeMark(Math.max(readMark(), ...list.map((f) => f.mtime)));
    note.hidden = false;
    note.textContent = `ZIP of ${list.length} file(s), ${size(bytesOf(list))} — the browser saves it as it arrives.`;
    draw();
  }

  function draw() {
    const mark = readMark();
    const fresh = files.filter((f) => f.mtime > mark);
    const shown = visible();
    const picked = files.filter((f) => selected.has(f.path));

    primary.textContent = fresh.length
      ? `Download ${fresh.length} new · ${size(bytesOf(fresh))}`
      : "No new outputs since your last download";
    primary.disabled = !fresh.length;
    primary.style.opacity = fresh.length ? 1 : 0.5;
    primary.onclick = () => start(fresh, true);

    selBtn.textContent = `Selected (${picked.length})`;
    selBtn.disabled = !picked.length;
    selBtn.style.opacity = picked.length ? 1 : 0.5;
    selBtn.onclick = () => start(picked, false);
    allBtn.textContent = `All ${shown.length}`;
    allBtn.onclick = () => start(shown, filter === "all");
    clearBtn.style.display = picked.length ? "" : "none";
    clearBtn.onclick = () => { selected.clear(); draw(); };

    const counts = { all: files.length };
    for (const f of files) counts[f.kind] = (counts[f.kind] || 0) + 1;
    chips.replaceChildren(...["all", "image", "video", "audio", "other"]
      .filter((k) => k === "all" || counts[k])
      .map((k) => el("button", {
        style: { ...buttonStyle, padding: "3px 10px", borderRadius: "999px", fontSize: "12px",
          ...(filter === k ? { background: "var(--fg-color, #eee)", color: "var(--comfy-menu-bg, #222)" } : {}) },
        onclick: () => { filter = k; limit = 60; draw(); },
      }, `${k === "all" ? "All" : k[0].toUpperCase() + k.slice(1) + "s"} ${counts[k]}`)));

    summary.textContent = files.length
      ? `${files.length} file(s), ${size(bytesOf(files))} on the pod · click to select, ↓ saves one`
      : "No outputs yet. Results appear here as soon as a job finishes.";

    grid.replaceChildren(...shown.slice(0, limit).map((f) => {
      const on = selected.has(f.path);
      const isNew = f.mtime > mark;
      let media;
      if (f.kind === "image") {
        media = el("img", { src: viewUrl(f.path, true), loading: "lazy", alt: f.path });
      } else if (f.kind === "video") {
        // "#t=0.1" makes the browser seek and paint a real frame; plain preload=metadata left
        // most tiles black on a RunPod pod (2026-09-14).
        media = el("video", { src: `${viewUrl(f.path)}#t=0.1`, preload: "metadata", muted: "", playsinline: "",
          onmouseenter: (e) => e.target.play().catch(() => {}), onmouseleave: (e) => e.target.pause() });
      } else {
        media = el("div", { style: { display: "grid", placeItems: "center", fontSize: "11px", opacity: 0.7 } },
          f.path.split(".").pop().toUpperCase());
      }
      Object.assign(media.style, { width: "100%", height: "100%", objectFit: "cover", display: media.style.display || "block" });
      const save = el("a", { href: viewUrl(f.path), download: f.path.split("/").pop(), title: "Download this file",
        onclick: (e) => e.stopPropagation(),
        style: { position: "absolute", right: "4px", bottom: "4px", width: "22px", height: "22px",
          borderRadius: "4px", background: "rgba(0,0,0,.65)", color: "#fff", textAlign: "center",
          lineHeight: "22px", textDecoration: "none", fontSize: "13px" } }, "↓");
      const tags = el("div", { style: { position: "absolute", left: "4px", top: "4px", display: "flex", gap: "3px" } });
      if (isNew) tags.append(el("span", { style: { background: "#2e7d32", color: "#fff", fontSize: "10px",
        padding: "1px 5px", borderRadius: "3px" } }, "NEW"));
      if (f.kind === "video") tags.append(el("span", { style: { background: "rgba(0,0,0,.65)", color: "#fff",
        fontSize: "10px", padding: "1px 5px", borderRadius: "3px" } }, "▶"));
      return el("div", {
        title: `${f.path}\n${size(f.size)} · ${new Date(f.mtime * 1000).toLocaleString()}`,
        onclick: () => { on ? selected.delete(f.path) : selected.add(f.path); draw(); },
        style: { position: "relative", aspectRatio: "1", overflow: "hidden", borderRadius: "6px", cursor: "pointer",
          background: "var(--comfy-input-bg, #222)",
          outline: on ? "3px solid #4caf50" : "1px solid var(--border-color, #444)", outlineOffset: on ? "-3px" : "-1px" },
      }, media, tags, save);
    }));
    more.style.display = shown.length > limit ? "" : "none";
    more.textContent = `Show more (${shown.length - limit} left)`;
  }

  async function refresh() {
    if (!container.isConnected) return;
    try {
      const data = await (await api.fetchApi("/aiangel/outputs")).json();
      const sig = (list) => list.map((f) => `${f.path}:${f.size}:${f.mtime}`).join("|");
      if (files.length && sig(files) === sig(data.files)) return; // unchanged: keep videos playing
      files = data.files;
      for (const p of [...selected]) if (!files.some((f) => f.path === p)) selected.delete(p);
      draw();
    } catch { /* pod busy or restarting; the next refresh tries again */ }
  }

  more.onclick = () => { limit += 60; draw(); };
  const origin = location.origin + location.pathname.replace(/\/$/, "");
  cmd.value = `python pull.py ${origin} ./aiangel-outputs`;
  const copy = el("button", { style: buttonStyle, onclick: async () => {
    try { await navigator.clipboard.writeText(cmd.value); copy.textContent = "Copied"; }
    catch { cmd.select(); }
  } }, "Copy command");
  const getScript = el("a", { href: api.apiURL("/aiangel/pull.py"), download: "pull.py",
    style: { ...buttonStyle, textDecoration: "none", display: "inline-block" } }, "Get pull.py");

  container.replaceChildren(el("div",
    { style: { display: "flex", flexDirection: "column", gap: "10px", padding: "12px" } },
    el("div", { style: { display: "flex", justifyContent: "space-between", alignItems: "center" } },
      el("div", { style: { fontWeight: "600" } }, "Outputs"),
      el("button", { style: { ...buttonStyle, padding: "3px 10px" }, onclick: refresh }, "Refresh")),
    primary,
    el("div", { style: { display: "flex", gap: "8px", flexWrap: "wrap" } }, selBtn, allBtn, clearBtn),
    note,
    chips, summary, grid, more,
    el("details", { style: { fontSize: "12px" } },
      el("summary", { style: { cursor: "pointer", fontWeight: "600" } }, "Sync everything to your computer"),
      el("div", { style: { display: "flex", flexDirection: "column", gap: "6px", marginTop: "8px" } },
        el("div", { style: { opacity: 0.8 } },
          "For big batches: pull.py copies all results several files at a time, skips what you already have, and resumes cut-off files. Needs Python 3.9+."),
        cmd,
        el("div", { style: { display: "flex", gap: "8px" } }, getScript, copy)))));

  refresh();
  const onDone = () => (container.isConnected ? setTimeout(refresh, 500) : api.removeEventListener("executed", onDone));
  api.addEventListener("executed", onDone);
  const timer = setInterval(() => (container.isConnected ? refresh() : clearInterval(timer)), 15000);
}

app.registerExtension({
  name: "aiangel.modelList",
  setup() {
    app.extensionManager.registerSidebarTab({
      id: "aiangel-outputs",
      icon: "pi pi-images",
      title: "Outputs",
      tooltip: "Download results in one ZIP, or sync them all to your computer",
      type: "custom",
      render: renderOutputs,
    });
    app.extensionManager.registerSidebarTab({
      id: "aiangel-model-list",
      icon: "pi pi-cloud-download",
      title: "Model list",
      tooltip: "Download a list of models (Civitai / Hugging Face)",
      type: "custom",
      render,
    });
  },
});
