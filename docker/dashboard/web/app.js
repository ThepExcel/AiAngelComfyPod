/* AI Angel ComfyPod dashboard front end. No build step, no framework.
   Contract: docs/dashboard-api.md. `?demo` renders built-in sample data without a server. */
(() => {
  "use strict";

  const DEMO = new URLSearchParams(location.search).has("demo");
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
  const el = (tag, attrs = {}, ...kids) => {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v == null || v === false) continue;
      if (k === "class") n.className = v;
      else if (k === "text") n.textContent = v;
      else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
      else n.setAttribute(k, v === true ? "" : v);
    }
    for (const kid of kids.flat()) if (kid != null) n.append(kid.nodeType ? kid : String(kid));
    return n;
  };

  const GB = 1024 ** 3;
  const fmtBytes = (b) => {
    if (b == null) return "—";
    if (b >= GB) return (b / GB).toFixed(b >= 100 * GB ? 0 : 1) + " GB";
    if (b >= 1024 ** 2) return (b / 1024 ** 2).toFixed(0) + " MB";
    if (b >= 1024) return (b / 1024).toFixed(0) + " KB";
    return b + " B";
  };
  const fmtDur = (s) => {
    if (s == null) return "—";
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
    return h ? `${h}h ${m}m` : m ? `${m}m ${Math.floor(s % 60)}s` : `${Math.floor(s)}s`;
  };
  const fmtAgo = (t) => {
    const s = Date.now() / 1000 - t;
    if (s < 60) return "just now";
    if (s < 3600) return Math.floor(s / 60) + " min ago";
    if (s < 86400) return Math.floor(s / 3600) + " h ago";
    return new Date(t * 1000).toLocaleDateString();
  };
  const pct = (a, b) => (b ? Math.max(0, Math.min(100, (a / b) * 100)) : 0);

  let toastTimer;
  const toast = (text, err = false) => {
    const t = $("#toast");
    t.textContent = text;
    t.classList.toggle("err", err);
    t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (t.hidden = true), 3200);
  };
  const copy = async (text, what) => {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const a = el("textarea", {}, text);
      document.body.append(a);
      a.select();
      document.execCommand("copy");
      a.remove();
    }
    toast(`${what} copied`);
  };

  /* ---------------- API ---------------- */
  async function api(path, body) {
    if (DEMO) return demoApi(path, body);
    const opt = body === undefined ? {} : {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    };
    const r = await fetch("api/" + path, opt);
    let data = {};
    try { data = await r.json(); } catch { /* empty body */ }
    if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
    return data;
  }
  const fileUrl = (p, download) =>
    DEMO ? "" : `api/outputs/file?path=${encodeURIComponent(p)}${download ? "&download=1" : ""}`;

  /* ---------------- tabs + keyboard ---------------- */
  const TABS = ["overview", "models", "outputs", "keys", "logs"];
  function showTab(name) {
    for (const t of TABS) $("#tab-" + t).hidden = t !== name;
    for (const b of $$(".tabs button")) b.setAttribute("aria-selected", b.dataset.tab === name);
    history.replaceState(null, "", "#" + name + (DEMO ? "" : ""));
    if (name === "outputs") loadOutputs();
    if (name === "logs") loadLog();
  }
  $$(".tabs button").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));
  $$("[data-goto]").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.goto)));
  document.addEventListener("keydown", (e) => {
    if (e.target.closest("input, textarea, select") || e.metaKey || e.ctrlKey || e.altKey) return;
    const i = Number(e.key);
    if (i >= 1 && i <= TABS.length) showTab(TABS[i - 1]);
  });

  /* ---------------- state render ---------------- */
  let state = null;
  const HERO = {
    ready: ["ComfyUI is ready", "Open it in a new tab. Nothing here stops while you work there."],
    starting: ["ComfyUI is starting", "Usually under a minute. Models keep downloading in the background either way."],
    down: ["ComfyUI is stopped", "Restart it here, or read the ComfyUI log to see why it stopped."],
  };

  function renderState(s) {
    state = s;
    const comfy = s.services.find((x) => x.key === "comfyui") || {};
    $("#podId").textContent = s.pod.id || "local";
    const [title, sub] = HERO[comfy.state] || HERO.down;
    const h1 = $("#heroTitle");
    const [lead, word] = [title.slice(0, title.lastIndexOf(" ") + 1), title.slice(title.lastIndexOf(" ") + 1)];
    const wordClass = { ready: "word-ok", starting: "word-run" }[comfy.state] || "word-bad";
    h1.replaceChildren(el("span", { class: "dot " + (comfy.state || "down"), "aria-hidden": "true" }),
      lead, el("span", { class: wordClass, text: word }));
    $("#heroSub").textContent = sub;
    for (const a of [$("#openComfy"), $("#openComfyTop")]) {
      a.href = comfy.url || "#";
      a.classList.toggle("is-disabled", comfy.state !== "ready");
    }

    const p = s.pod;
    const sized = (d) => (d && d.total != null ? d : null);
    const wsElastic = !!p.disk?.workspace?.elastic;
    const ws = sized(p.disk?.workspace), ct = sized(p.disk?.container);
    const meter = (k, v, sub, fill, warn, color) =>
      el("div", { class: "meter", style: color ? `--c:${color}` : null },
        el("div", { class: "k", text: k }),
        el("div", { class: "v" }, v, sub ? el("small", {}, " " + sub) : null),
        fill == null ? null : el("div", { class: "bar-track" },
          el("div", { class: "bar-fill" + (warn ? " warn" : ""), style: `width:${fill}%` })));
    const gpuShort = (p.gpu || "no GPU").replace(/^NVIDIA\s+/, "").replace(/ Blackwell.*$/, "");
    $("#meters").replaceChildren(
      meter(p.gpu_util != null ? `GPU · ${p.gpu_util}% busy` : "GPU", gpuShort, "",
        p.gpu_util != null ? p.gpu_util : null, false, "var(--violet)"),
      meter("VRAM", p.vram_total_mb ? fmtBytes(p.vram_used_mb * 1024 ** 2) : "—",
        p.vram_total_mb ? "/ " + fmtBytes(p.vram_total_mb * 1024 ** 2) : "",
        p.vram_total_mb ? pct(p.vram_used_mb, p.vram_total_mb) : null, false, "var(--cyan)"),
      meter("Volume /workspace", ws ? fmtBytes(ws.total - ws.used) : wsElastic ? "Elastic" : "—",
        ws ? "free" : wsElastic ? "grows as you store" : "",
        ws ? pct(ws.used, ws.total) : null, ws && ws.total - ws.used < 10 * GB, "var(--wait)"),
      meter("Container disk", ct ? fmtBytes(ct.total - ct.used) : "—", ct ? "free" : "",
        ct ? pct(ct.used, ct.total) : null, ct && ct.total - ct.used < 3 * GB, "var(--run)"),
      meter("Uptime", fmtDur(p.uptime_s), "", null, false, "var(--ok)"),
      meter("Image", p.cuda ? "CUDA " + p.cuda : "—", p.image || "", null, false, "var(--pink)"),
    );

    renderServices(s.services);
    renderPresets(s);
    renderJobs(s.jobs);
    renderKeys(s.keys);
    $("#outputsSub").textContent =
      `${s.outputs.count} files · ${fmtBytes(s.outputs.bytes)}. Pick files, or take them all, as ZIP.`;
  }

  function renderServices(list) {
    const rows = list.map((svc) => {
      const row = el("div", { class: "svc" },
        el("span", { class: "state " + svc.state, title: svc.state }),
        el("div", {}, el("span", { class: "name", text: svc.name }), " ",
          el("span", { class: "port", text: ":" + svc.port })),
        el("a", { class: "btn", href: svc.url, target: "_blank", rel: "noopener" }, "Open ↗"));
      if (svc.secret) {
        let shown = false;
        const code = el("code", { text: "••••••••••••" });
        const toggle = el("button", {
          class: "mini", text: "Show",
          onclick: () => { shown = !shown; code.textContent = shown ? svc.secret : "••••••••••••"; toggle.textContent = shown ? "Hide" : "Show"; },
        });
        row.append(el("div", { class: "secret" },
          svc.user ? el("span", {}, `user ${svc.user} ·`) : null,
          svc.key === "jupyter" ? "token" : "password", code, toggle,
          el("button", { class: "mini", text: "Copy", onclick: () => copy(svc.secret, svc.name + " password") })));
      }
      return row;
    });
    $("#services").replaceChildren(...rows);
  }

  const fileState = (f) => {
    if (f.state === "have") return fmtBytes(f.size);
    if (f.state === "downloading") return `${pct(f.have_bytes, f.size).toFixed(0)}%`;
    return f.state;
  };

  function renderPresets(s) {
    $("#modelsEnv").textContent = "MODELS=" + (s.models_env || "(empty)");
    const summary = s.presets.filter((p) => p.in_env).map((p) => {
      const total = p.files.reduce((a, f) => a + f.size, 0);
      const have = p.files.reduce((a, f) => a + Math.min(f.have_bytes, f.size), 0);
      const all = p.files.every((f) => f.state === "have");
      return el("div", { class: "summary-row" },
        el("span", { class: "mono", text: p.name }),
        el("div", { class: "bar-track" }, el("div", { class: "bar-fill " + (all ? "ok" : "run"), style: `width:${pct(have, total)}%` })),
        el("span", { class: "mono small " + (all ? "" : "dim"), text: all ? fmtBytes(total) : `${fmtBytes(have)} / ${fmtBytes(total)}` }));
    });
    $("#presetSummary").replaceChildren(...(summary.length ? summary : [el("p", { class: "empty", text: "No presets set. Add one in Models." })]));

    const cards = s.presets.map((p) => {
      const total = p.files.reduce((a, f) => a + f.size, 0);
      const missing = p.files.filter((f) => f.state === "missing" || f.state === "failed");
      const busy = p.files.some((f) => f.state === "downloading" || f.state === "queued");
      const btn = missing.length
        ? el("button", { class: "btn" + (busy ? "" : " primary"), disabled: busy, onclick: () => addPreset(p.name) },
          busy ? "Downloading…" : `Download ${fmtBytes(missing.reduce((a, f) => a + f.size, 0))}`)
        : el("span", { class: "tag " + (busy ? "run" : "ok"), text: busy ? "downloading" : "ready" });
      return el("div", { class: "preset" },
        el("div", { class: "preset-head" },
          el("span", { class: "preset-name", text: p.name }),
          p.in_env ? el("span", { class: "tag env", text: "MODELS" }) : null,
          el("span", { class: "preset-size", text: fmtBytes(total) }),
          btn),
        el("div", { class: "files" }, p.files.map((f) =>
          el("div", { class: "file" },
            el("span", { class: "fname", title: `${f.folder}/${f.name}`, text: `${f.folder}/${f.name}` }),
            el("span", { class: "fstate " + f.state, text: fileState(f) }),
            f.state === "downloading" ? el("div", { class: "bar-track" },
              el("div", { class: "bar-fill run", style: `width:${pct(f.have_bytes, f.size)}%` })) : null))));
    });
    $("#presets").replaceChildren(...cards);
  }

  function renderJobs(jobs) {
    const active = jobs.filter((j) => !["done", "failed"].includes(j.state)).length;
    $("#jobsHint").textContent = jobs.length ? `${active} running or queued` : "";
    const rows = [...jobs].reverse().map((j) =>
      el("div", { class: "job" },
        el("span", { class: "label", title: j.url, text: j.label || j.url }),
        el("span", { class: "jstate " + j.state, text: j.state === "downloading" && j.size ? `${pct(j.done_bytes, j.size).toFixed(0)}%` : j.state }),
        j.state === "downloading" ? el("div", { class: "bar-track" }, el("div", { class: "bar-fill run", style: `width:${pct(j.done_bytes, j.size)}%` })) : null,
        j.message && j.state === "failed" ? el("span", { class: "jmsg", text: j.message }) : null));
    $("#jobs").replaceChildren(...(rows.length ? rows : [el("p", { class: "empty", text: "Nothing downloading." })]));
  }

  function renderKeys(keys) {
    for (const pill of $$(".state-pill")) {
      const v = keys[pill.dataset.for];
      pill.textContent = v ? "saved " + v : "not set";
      pill.classList.toggle("set", !!v);
    }
  }

  /* ---------------- actions ---------------- */
  async function addPreset(name) {
    try {
      const r = await api("preset", { name });
      toast(r.queued ? `${name}: ${r.queued} file(s) queued` : `${name} is already on the volume`);
      poll();
    } catch (e) { toast(e.message, true); }
  }

  $("#queueLinks").addEventListener("click", async () => {
    const text = $("#linkText").value.trim();
    const msg = $("#linkMsg");
    if (!text) { msg.textContent = "Paste at least one link."; msg.className = "msg err"; return; }
    try {
      const r = await api("download", { text });
      msg.textContent = `${r.queued} download(s) queued.`;
      msg.className = "msg";
      $("#linkText").value = "";
      poll();
    } catch (e) { msg.textContent = e.message; msg.className = "msg err"; }
  });

  $("#loadNsfw").addEventListener("click", async () => {
    try {
      const r = await api("kit/nsfw");
      const box = $("#linkText");
      box.value = (box.value.trim() ? box.value.trim() + "\n" : "") + r.text.trim();
      $("#linkMsg").textContent = "Adult model list added. Civitai files need your Civitai key (Keys tab).";
      $("#linkMsg").className = "msg";
    } catch (e) { toast(e.message, true); }
  });

  $("#restartComfy").addEventListener("click", async (e) => {
    if (!confirm("Restart ComfyUI? A running job will stop.")) return;
    e.target.disabled = true;
    try { await api("comfy/restart", {}); toast("Restarting ComfyUI…"); poll(); }
    catch (err) { toast(err.message, true); }
    setTimeout(() => (e.target.disabled = false), 5000);
  });

  for (const card of $$(".key-card")) {
    const input = $("input", card);
    const send = async (value) => {
      try {
        const keys = await api("keys", { [card.dataset.site]: value });
        renderKeys(keys);
        input.value = "";
        toast(value === "-" ? "Key removed" : "Key saved");
      } catch (e) { toast(e.message, true); }
    };
    $(".save-key", card).addEventListener("click", () => input.value.trim() && send(input.value.trim()));
    $(".clear-key", card).addEventListener("click", () => send("-"));
  }

  /* ---------------- outputs ---------------- */
  let files = [];
  const selected = new Set();
  let kind = "all";

  async function loadOutputs() {
    try {
      files = (await api("outputs")).files;
    } catch (e) { toast(e.message, true); return; }
    for (const p of [...selected]) if (!files.some((f) => f.path === p)) selected.delete(p);
    renderGallery();
    renderLatest();
  }

  function tile(f, small = false) {
    const media = el("div", { class: "media" });
    if (!DEMO && f.kind === "image") media.append(el("img", { src: fileUrl(f.path), loading: "lazy", alt: "" }));
    else if (!DEMO && f.kind === "video") {
      const v = el("video", { src: fileUrl(f.path) + "#t=0.5", preload: "metadata", muted: true, playsinline: true, loop: true });
      v.muted = true;
      media.append(v);
      media.addEventListener("mouseenter", () => v.play().catch(() => {}));
      media.addEventListener("mouseleave", () => v.pause());
    } else media.append(el("span", { class: "glyph", text: f.kind === "other" ? f.path.split(".").pop() : f.kind }));
    if (f.kind !== "other") media.append(el("span", { class: "kind " + f.kind, text: f.kind }));
    const name = f.path.split("/").pop();
    const t = el("div", { class: "tile" + (selected.has(f.path) ? " selected" : ""), tabindex: 0, role: "button", "aria-pressed": selected.has(f.path) },
      media,
      small ? null : el("span", { class: "check", text: "✓", "aria-hidden": "true" }),
      small ? null : el("a", { class: "dl", href: fileUrl(f.path, true), download: name, title: "Download this file", onclick: (e) => e.stopPropagation() }, "↓"),
      el("div", { class: "meta" },
        el("span", { class: "tname", title: f.path, text: name }),
        el("span", { class: "tsub", text: `${fmtBytes(f.size)} · ${fmtAgo(f.mtime)}` })));
    const toggle = () => {
      if (small) { showTab("outputs"); return; }
      selected.has(f.path) ? selected.delete(f.path) : selected.add(f.path);
      t.classList.toggle("selected", selected.has(f.path));
      t.setAttribute("aria-pressed", selected.has(f.path));
      updateSel();
    };
    t.addEventListener("click", toggle);
    t.addEventListener("keydown", (e) => { if (e.key === " " || e.key === "Enter") { e.preventDefault(); toggle(); } });
    return t;
  }

  const visible = () => files.filter((f) => kind === "all" || f.kind === kind);
  function renderGallery() {
    const list = visible();
    $("#gallery").replaceChildren(...(list.length ? list.map((f) => tile(f)) : [el("p", { class: "empty", text: "No outputs yet. Run a workflow in ComfyUI; results appear here." })]));
    updateSel();
  }
  function renderLatest() {
    const list = files.filter((f) => f.kind !== "other").slice(0, 10);
    $("#latestOutputs").replaceChildren(...(list.length ? list.map((f) => tile(f, true)) : [el("p", { class: "empty", text: "Nothing generated yet." })]));
  }
  function chosen() {
    return selected.size ? files.filter((f) => selected.has(f.path)) : visible();
  }
  function updateSel() {
    const c = chosen();
    const bytes = c.reduce((a, f) => a + f.size, 0);
    $("#selInfo").textContent = selected.size
      ? `${selected.size} selected · ${fmtBytes(bytes)}`
      : `0 selected · ZIP = all ${c.length} (${fmtBytes(bytes)})`;
    $("#parts").hidden = true;
  }

  $$("#kindFilter button").forEach((b) => b.addEventListener("click", () => {
    kind = b.dataset.kind;
    $$("#kindFilter button").forEach((x) => x.setAttribute("aria-pressed", x === b));
    renderGallery();
  }));
  $("#selectAll").addEventListener("click", () => { visible().forEach((f) => selected.add(f.path)); renderGallery(); });
  // "New since last ZIP": this browser remembers when it last downloaded a ZIP from this pod.
  const LAST_KEY = "aiangel-last-zip-" + location.host;
  const lastZip = () => { try { return Number(localStorage.getItem(LAST_KEY)) || 0; } catch { return 0; } };
  $("#selectNew").addEventListener("click", () => {
    const since = lastZip();
    selected.clear();
    visible().filter((f) => f.mtime > since).forEach((f) => selected.add(f.path));
    renderGallery();
    toast(since ? `${selected.size} new since your last ZIP (${fmtAgo(since)})` : `No ZIP downloaded from this browser yet: all ${selected.size} selected`);
  });
  $("#selectNone").addEventListener("click", () => { selected.clear(); renderGallery(); });

  function splitParts(list, rule) {
    if (rule === "0") return [list];
    const parts = [];
    let cur = [], size = 0;
    const byCount = rule.startsWith("count");
    const limit = byCount ? Number(rule.slice(5)) : Number(rule) * GB;
    for (const f of [...list].sort((a, b) => a.mtime - b.mtime)) {
      const over = byCount ? cur.length >= limit : cur.length && size + f.size > limit;
      if (over) { parts.push(cur); cur = []; size = 0; }
      cur.push(f);
      size += f.size;
    }
    if (cur.length) parts.push(cur);
    return parts;
  }

  function postZip(list) {
    try {
      const newest = Math.max(...list.map((f) => f.mtime));
      if (newest > lastZip()) localStorage.setItem(LAST_KEY, String(newest));
    } catch { /* storage blocked: the button just selects everything next time */ }
    if (DEMO) { toast(`Demo: would download ${list.length} files`); return; }
    const form = el("form", { method: "POST", action: "api/outputs/zip", hidden: true },
      el("input", { name: "files", value: JSON.stringify(list.map((f) => f.path)) }));
    document.body.append(form);
    form.submit();
    form.remove();
  }

  $("#zipSelected").addEventListener("click", () => {
    const list = chosen();
    if (!list.length) { toast("No outputs to download", true); return; }
    const parts = splitParts(list, $("#partSize").value);
    if (parts.length === 1) { postZip(parts[0]); toast(`Preparing ZIP of ${list.length} files…`); return; }
    const box = $("#parts");
    box.replaceChildren(el("span", { class: "lead", text: `${parts.length} parts, oldest first. Download each:` }),
      ...parts.map((p, i) => {
        const b = el("button", { class: "btn", text: `Part ${i + 1} · ${p.length} files · ${fmtBytes(p.reduce((a, f) => a + f.size, 0))}` });
        b.addEventListener("click", () => { postZip(p); b.classList.add("ghost"); b.textContent = "✓ " + b.textContent; });
        return b;
      }));
    box.hidden = false;
  });

  /* ---------------- logs ---------------- */
  let logName = "boot";
  async function loadLog() {
    const box = $("#logBox");
    try {
      const r = await api(`logs?name=${logName}&lines=400`);
      const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
      const tone = (line) =>
        /FAILED|ERROR|Traceback|Exception|exited \(code [1-9]/i.test(line) ? "l-bad"
          : /WARNING|MISMATCH|unknown preset/i.test(line) ? "l-warn"
            : /READY|synced|\bgot\b|\bhave\b|started/i.test(line) ? "l-ok"
              : /download|fetching|starting|install/i.test(line) ? "l-run" : null;
      box.replaceChildren(...(r.lines.length
        ? r.lines.map((line) => el("span", { class: tone(line) }, line + "\n"))
        : ["(empty)"]));
      if (atBottom) box.scrollTop = box.scrollHeight;
    } catch (e) { box.textContent = e.message; }
  }
  $$("#logPick button").forEach((b) => b.addEventListener("click", () => {
    logName = b.dataset.log;
    $$("#logPick button").forEach((x) => x.setAttribute("aria-pressed", x === b));
    $("#logBox").textContent = "Loading…";
    loadLog();
  }));

  /* ---------------- polling ---------------- */
  let pollTimer, outputsTick = 0;
  async function poll() {
    clearTimeout(pollTimer);
    try {
      renderState(await api("state"));
      if (!$("#tab-logs").hidden) loadLog();
      if (outputsTick++ % 5 === 0 && $("#tab-outputs").hidden) loadOutputs();
    } catch (e) {
      $("#heroTitle").textContent = "Dashboard lost the pod";
      $("#heroSub").textContent = e.message + " · retrying";
    }
    pollTimer = setTimeout(poll, document.hidden ? 10000 : 2000);
  }
  document.addEventListener("visibilitychange", () => !document.hidden && poll());

  const start = TABS.includes(location.hash.slice(1)) ? location.hash.slice(1) : "overview";
  showTab(start);
  poll();

  /* ---------------- demo data ---------------- */
  function demoApi(path) {
    const now = Date.now() / 1000;
    if (path === "state") {
      const t = (now % 60) / 60;
      return Promise.resolve({
        pod: { id: "l45bp7l06j9ekz", gpu: "NVIDIA RTX PRO 6000 Blackwell Server Edition", vram_used_mb: 41210, vram_total_mb: 97887, gpu_util: 97, cuda: "13.0", image: "d851622", uptime_s: 812, disk: { workspace: { used: 46.2 * GB, total: 150 * GB }, container: { used: 9.4 * GB, total: 30 * GB } } },
        services: [
          { key: "comfyui", name: "ComfyUI", port: 8188, url: "#", state: "ready" },
          { key: "filebrowser", name: "FileBrowser", port: 8080, url: "#", state: "ready", user: "admin", secret: "6bce9425055c16d9" },
          { key: "jupyter", name: "JupyterLab", port: 8888, url: "#", state: "ready", secret: "9792a18f1b924b14" },
        ],
        models_env: "h3core,h3upscaler,aiangelh3",
        presets: [
          { name: "h3core", in_env: true, files: [
            { folder: "text_encoders", name: "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors", size: 15687142551, have_bytes: 15687142551, state: "have" },
            { folder: "vae", name: "minimax_h3_video_vae_fp16.safetensors", size: 5207808496, have_bytes: 5207808496, state: "have" },
            { folder: "vae", name: "minimax_h3_audio_vae_fp32.safetensors", size: 605254808, have_bytes: 605254808, state: "have" }] },
          { name: "aiangelh3", in_env: true, files: [
            { folder: "diffusion_models", name: "AiAngelH3-v1-int8.safetensors", size: 20970427336, have_bytes: 20970427336, state: "have" }] },
          { name: "h3upscaler", in_env: true, files: [
            { folder: "latent_upscale_models", name: "minimax_h3_latent_upscaler_3d_bf16.safetensors", size: 690592992, have_bytes: 690592992, state: "have" }] },
          { name: "scail", in_env: false, files: [
            { folder: "diffusion_models", name: "wan2.1_scail2_14B_fp8.safetensors", size: 16 * GB, have_bytes: t * 16 * GB, state: "downloading" },
            { folder: "text_encoders", name: "umt5_xxl_fp8_e4m3fn_scaled.safetensors", size: 6.7 * GB, have_bytes: 0, state: "queued" }] },
          { name: "krea2", in_env: false, files: [
            { folder: "diffusion_models", name: "krea2_fp8.safetensors", size: 19 * GB, have_bytes: 0, state: "missing" }] },
        ],
        jobs: [
          { id: 1, label: "loras/mystic_xxx_v2.safetensors", url: "https://civitai.com/models/1", state: "done", size: 1.2 * GB, done_bytes: 1.2 * GB },
          { id: 2, label: "loras/private_repo.safetensors", url: "https://huggingface.co/x", state: "failed", message: "HTTP 401: this repo is gated, save a Hugging Face token in Keys" },
          { id: 3, label: "diffusion_models/wan2.1_scail2_14B_fp8.safetensors", url: "https://huggingface.co/y", state: "downloading", size: 16 * GB, done_bytes: t * 16 * GB },
        ],
        keys: { civitai: "3f9a…c21e", huggingface: null },
        outputs: { count: 14, bytes: 51 * 1024 ** 2 },
      });
    }
    if (path === "outputs") {
      return Promise.resolve({ files: Array.from({ length: 14 }, (_, i) => ({
        path: `AiAngel/${i % 3 ? "aiangelh3" : "aiangelh3-extend"}_${String(14 - i).padStart(5, "0")}_.${i % 4 === 3 ? "png" : "mp4"}`,
        size: (i % 4 === 3 ? 1.1 : 2.4 + i * 0.3) * 1024 ** 2, mtime: now - i * 900, kind: i % 4 === 3 ? "image" : "video" })) });
    }
    if (path.startsWith("logs")) {
      return Promise.resolve({ name: logName, lines: [
        "[aiangel 2026-09-15T17:12:41Z +0s] boot start pod=l45bp7l06j9ekz data=/workspace/aiangel",
        "[aiangel 2026-09-15T17:12:41Z +0s] models at /workspace/aiangel/models",
        "[aiangel 2026-09-15T17:13:52Z +71s] custom nodes synced from image",
        "[aiangel 2026-09-15T17:13:55Z +74s] dashboard on :8189",
        "  FileBrowser  :8080  user admin  password ••••",
        "[aiangel 2026-09-15T17:14:02Z +81s] downloading models in background",
        "[aiangel 2026-09-15T17:14:26Z +105s] ComfyUI READY on :8188"] });
    }
    if (path === "kit/nsfw") return Promise.resolve({ text: "loras https://civitai.com/models/123?modelVersionId=456" });
    return Promise.resolve({ queued: 1, ok: true, civitai: "3f9a…c21e", huggingface: null });
  }
})();
