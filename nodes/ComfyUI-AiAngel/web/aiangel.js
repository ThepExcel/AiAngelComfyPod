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

app.registerExtension({
  name: "aiangel.modelList",
  setup() {
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
