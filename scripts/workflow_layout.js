// Arrange and save the template's H3 workflows from inside a live ComfyUI page.
//
// Flow: build API graphs (uv run python scripts/h3_workflows.py OUT_DIR), upload each
// `h3-clip.api.json` / `h3-extend.api.json` to the pod's input folder (POST /upload/image), open the
// pod's ComfyUI in a browser, paste this whole file into the devtools console (or a
// javascript_exec), then run:
//
//   await aiBuild('clip')    // loads, lays out, saves user/default/workflows/AiAngel H3 - Clip.json
//   await aiBuild('extend')
//   await app.queuePrompt(0, 1)   // prove the saved UI graph runs
//
// Pull the saved files into nodes/ComfyUI-AiAngel/example_workflows/ with
// GET /api/userdata/workflows%2FAiAngel%20H3%20-%20Clip.json (and ... Extend.json).

window.aiLayout = async function (apiFile, name, columns) {
  const api = await (await fetch('/view?filename=' + apiFile + '&type=input')).json();
  await app.loadApiJson(api, name);
  await new Promise((r) => setTimeout(r, 800));
  const g = app.graph;
  const byTitle = (t) => g._nodes.find((n) => n.title === t) || g._nodes.find((n) => n.type === t);
  const GAP = 30, TITLE = 36, PAD = 20;
  let x = 0;
  const report = [];
  for (const col of columns) {
    let y = 70;
    const w = col.width;
    for (const item of col.nodes) {
      let n;
      if (item.note) {
        n = LiteGraph.createNode('MarkdownNote');
        g.add(n);
        n.title = item.title || 'Note';
        n.widgets[0].value = item.note;
      } else {
        n = byTitle(item.t);
        if (!n) { report.push('MISSING ' + item.t); continue; }
      }
      const min = n.computeSize();
      n.size = [w - 2 * PAD, Math.max(min[1], item.h || 0)];
      n.pos = [x + PAD, y + TITLE];
      y += n.size[1] + TITLE + GAP;
    }
    const grp = new LiteGraph.LGraphGroup(col.title);
    grp.pos = [x, 0];
    grp.size = [w, y + 10];
    grp.color = col.color;
    g.add(grp);
    x += w + 60;
  }
  const placed = new Set(columns.flatMap((c) => c.nodes.map((i) => i.t)));
  const leftovers = g._nodes
    .filter((n) => n.type !== 'MarkdownNote' && !placed.has(n.title) && !placed.has(n.type))
    .map((n) => n.id + ':' + n.type + ':' + n.title);
  app.canvas.setDirty(true, true);
  return { report, leftovers };
};

window.aiSave = async function (file) {
  const body = JSON.stringify(app.graph.serialize(), null, 1);
  const r = await fetch('/api/userdata/' + encodeURIComponent('workflows/' + file) + '?overwrite=true',
    { method: 'POST', body });
  return { status: r.status, bytes: body.length };
};

const NOTES = {
  howClip: `## AiAngel H3 · Clip (reference to video)

1. **Models** — start the pod with \`MODELS=h3\` in its environment variables (first boot downloads them).
2. **<Picture 1>** — upload the person / character image.
3. **Prompt** — edit the prompt box in *H3 Reference to Video*. Refer to images as \`<Picture 1>\`, \`<Picture 2>\` … in the order they are connected. Dialogue goes in \`<d>…</d>\`; for Thai write \`(S1) <d>[Thai] …</d>\`.
4. **Seconds** — 2 to 15. Frames snap to H3's 17k+5 grid for you.
5. **Run.** The video lands in the *Outputs* tab under \`AiAngel/\`.

**More references:** drag another *Load Image* into *H3 Reference to Video* — a new \`ref_image\` slot appears each time (up to 9 pictures, 3 videos, 3 audio clips).
**Your LoRA:** add *LoraLoaderModelOnly* between *Turbo LoRA* and *Comfy Kitchen attention*.`,
  howExtend: `## AiAngel H3 · Extend a clip

Continues a clip without a cut, for scenes longer than 15 s.

1. **Previous clip** — upload an H3 clip (24 fps). Size is taken from it.
2. **<Picture 1>** — the same character image you used before, so the face stays locked.
3. **Prompt** — start with *"A continuous shot from beginning to end."* and describe what happens next. The first ~1 s (the overlap) is the end of the previous clip.
4. **Overlap frames** — 22 (≈0.9 s) is the tested default; 5, 22 or 39.
5. **Seconds** — length of the new part including the overlap.
6. **Run.** The saved video is previous + new, cross-faded over the overlap, sound included. Feed it back in as *Previous clip* to keep going.`,
  speed: `### Measured defaults (RTX PRO 6000, 576×1024, 5 s)

| setting | seconds |
|---|---|
| plain | 46 |
| **+ Comfy Kitchen attention** (default) | **42** |
| + int8 video VAE (CUDA 12.8) | 54 · slower |
| + Spectrum at 4 steps | 42 · no effect |
| 15 s clip | 141 |
| extend 5 s onto a 5 s clip | 62 |

Width/height must be multiples of 32. 576×1024 for drafts; 720×1280 for finals.`,
  prompt: `### Structured prompt (H3 likes firm instructions)

\`\`\`
subject_definitions:
<Subject 1> is the woman in <Picture 1>. (face, hair, outfit)

summary:
[reference generation] One sentence: who, where, what.

retention_analysis:
<Subject 1>: fully_preserved - face, hairstyle and outfit stay identical.

detailed_description:
[Shot 1] 00:00-00:03: camera + action.
[Shot 1] 00:03-00:05: next action, dialogue <d>Hello!</d>

overall_soundscape:
ambience, sounds, voice character
\`\`\`
Guide: https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/docs/VIDEO_PROMPT_WRITING_GUIDE_ref_en.md`,
};

const MODELS_COL = { title: '2 · Models (MODELS=h3)', width: 420, color: '#a1309b', nodes: [
  { t: 'H3 model' }, { t: 'H3 text encoder' }, { t: 'Video VAE' }, { t: 'Audio VAE' },
  { t: 'Turbo LoRA (4 steps)' }, { t: 'Comfy Kitchen attention (faster)' }] };

const LAYOUTS = {
  clip: { api: 'h3-clip.api.json', name: 'AiAngel H3 - Clip', columns: [
    { title: 'Start here', width: 520, color: '#3f789e', nodes: [
      { note: NOTES.howClip, title: 'How to use', h: 330 }, { note: NOTES.prompt, title: 'Prompt template', h: 440 }] },
    { title: '1 · Your inputs', width: 560, color: '#8A8', nodes: [
      { t: '<Picture 1>', h: 420 }, { t: 'Seconds' }, { t: 'Frames (17k+5 grid)' }, { t: 'H3 Reference to Video', h: 520 }] },
    MODELS_COL,
    { title: '3 · Generate', width: 400, color: '#b58b2a', nodes: [
      { t: 'Seed' }, { t: 'KSamplerSelect' }, { t: 'BasicScheduler' }, { t: 'BasicGuider' }, { t: 'Sample' },
      { note: NOTES.speed, title: 'Speed notes', h: 360 }] },
    { title: '4 · Video', width: 560, color: '#444', nodes: [
      { t: 'Decode video' }, { t: 'Decode audio' }, { t: 'Create video' }, { t: 'Save video', h: 760 }] },
  ] },
  extend: { api: 'h3-extend.api.json', name: 'AiAngel H3 - Extend', columns: [
    { title: 'Start here', width: 520, color: '#3f789e', nodes: [
      { note: NOTES.howExtend, title: 'How to use', h: 360 }, { note: NOTES.prompt, title: 'Prompt template', h: 440 }] },
    { title: '1 · Your inputs', width: 560, color: '#8A8', nodes: [
      { t: 'Previous clip (24 fps)', h: 480 }, { t: '<Picture 1>', h: 380 }, { t: 'Overlap frames (5, 22, 39)' },
      { t: 'Seconds' }, { t: 'H3 Reference to Video', h: 520 }] },
    MODELS_COL,
    { title: '3 · Previous clip: head + tail', width: 420, color: '#3f6b5e', nodes: [
      { t: 'Previous clip parts' }, { t: 'Previous size + frame count' }, { t: 'Frames (17k+5 grid)' },
      { t: 'Head frames (total - overlap)' }, { t: 'Previous head frames' }, { t: 'Head seconds' },
      { t: 'Previous head audio' }, { t: 'Tail start (-overlap)' }, { t: 'Previous tail frames' },
      { t: 'Overlap seconds' }, { t: 'Tail start seconds' }, { t: 'Previous tail audio' }] },
    { title: '4 · Generate', width: 400, color: '#b58b2a', nodes: [
      { t: 'Anchor previous tail' }, { t: 'Seed' }, { t: 'KSamplerSelect' }, { t: 'BasicScheduler' },
      { t: 'BasicGuider' }, { t: 'Sample' }, { t: 'Decode video' }, { t: 'Decode audio' },
      { note: NOTES.speed, title: 'Speed notes', h: 360 }] },
    { title: '5 · Stitch + save', width: 560, color: '#444', nodes: [
      { t: 'New overlap frames' }, { t: 'Cross-fade overlap' }, { t: 'New frames after overlap' },
      { t: 'Head + cross-fade' }, { t: 'Full clip frames' }, { t: 'Full clip audio' }, { t: 'Create video' },
      { t: 'Save video', h: 760 }] },
  ] },
};

window.aiBuild = async function (kind) {
  const L = LAYOUTS[kind];
  const result = await aiLayout(L.api, L.name, L.columns);
  const saved = await aiSave(L.name + '.json');
  return { ...result, saved };
};
