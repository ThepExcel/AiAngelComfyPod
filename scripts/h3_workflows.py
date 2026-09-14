"""MiniMax H3 API graphs for the template's own workflows: one clip (ref2va) and clip extension.

Defaults come from the 2026-09-14 pod bench (RTX PRO 6000, 576x1024, 5 s): hybrid fl2va+ref2va b25,
ref2v 4-step turbo LoRA, Comfy Kitchen (int8) attention — 42 s vs 46 s without it, same look; the
int8 video VAE was slower on CUDA 12.8 (54 s), so the fp16 VAE is the default.

Extension follows the SEEDHUNTER v16 "seamless continuation" recipe: the last `overlap` frames and
their audio of the previous clip are anchored at frame 0 of a new ref2va generation, the overlap is
cross-faded 50/50, and previous head + blend + new tail are stitched into one video in the graph.

Only ComfyUI core nodes are used, so a graph runs on any ComfyUI >= 0.35.0 with the H3 models.
Every function returns an API-format dict; `refs` / `prev_video` are file names already in input/.
"""

from __future__ import annotations

UNET = "minimax_h3_hybrid_fl2va_ref2va_b25-49-int8.safetensors"
TEXT_ENCODER = "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"
VIDEO_VAE = "minimax_h3_video_vae_fp16.safetensors"
AUDIO_VAE = "minimax_h3_audio_vae_fp32.safetensors"
TURBO_LORA = "minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors"
# H3 only accepts frame counts on the 17k+5 grid at 24 fps
LENGTH_EXPR = "max(5, round(a * 24)) + (5 - (max(5, round(a * 24)) % 17)) % 17"

EXAMPLE_PROMPT = "\n".join(
    [
        "subject_definitions:",
        "<Subject 1> is the woman in <Picture 1>. Use <Picture 1> as the exact reference for her"
        " face, hair and outfit.",
        "",
        "summary:",
        "[reference generation] A cinematic vertical shot of <Subject 1> in a sunlit cafe.",
        "",
        "retention_analysis:",
        "<Subject 1>: fully_preserved - face, hairstyle, skin tone and outfit from <Picture 1>"
        " stay identical in every frame.",
        "",
        "detailed_description:",
        "[Shot 1] 00:00-00:05: Medium close-up. <Subject 1> sits by the window, looks up from her"
        " coffee, smiles at the camera and says <d>Good morning!</d>. Soft daylight, shallow"
        " depth of field.",
        "",
        "overall_soundscape:",
        "Quiet cafe ambience, cups clinking, her clear friendly voice.",
    ]
)


def _node(cls: str, **inputs) -> dict:
    return {"class_type": cls, "inputs": inputs}


TITLES = {
    "unet": "H3 model",
    "clip": "H3 text encoder",
    "vae": "Video VAE",
    "audio_vae": "Audio VAE",
    "lora0": "Turbo LoRA (4 steps)",
    "attention": "Comfy Kitchen attention (faster)",
    "ref0": "<Picture 1>",
    "seconds": "Seconds",
    "length": "Frames (17k+5 grid)",
    "r2v": "H3 Reference to Video",
    "prev": "Previous clip (24 fps)",
    "overlap": "Overlap frames (5, 22, 39)",
    "guide": "Anchor previous tail",
    "blend": "Cross-fade overlap",
    "save": "Save video",
    "parts": "Previous clip parts",
    "size": "Previous size + frame count",
    "head_len": "Head frames (total - overlap)",
    "prev_head": "Previous head frames",
    "tail_start": "Tail start (-overlap)",
    "prev_tail": "Previous tail frames",
    "tail_secs": "Overlap seconds",
    "neg_tail_secs": "Tail start seconds",
    "prev_tail_audio": "Previous tail audio",
    "head_secs": "Head seconds",
    "prev_head_audio": "Previous head audio",
    "new_overlap": "New overlap frames",
    "new_rest": "New frames after overlap",
    "join_a": "Head + cross-fade",
    "join": "Full clip frames",
    "join_audio": "Full clip audio",
    "noise": "Seed",
    "sample": "Sample",
    "decode": "Decode video",
    "decode_audio": "Decode audio",
    "video": "Create video",
}


def _numbered(g: dict) -> dict:
    """Readable build keys -> the numeric ids ComfyUI's UI expects, with titles for the canvas."""
    ids = {key: str(i) for i, key in enumerate(g, start=1)}
    out = {}
    for key, node in g.items():
        inputs = {
            k: [ids[v[0]], v[1]] if isinstance(v, list) and len(v) == 2 and v[0] in ids else v
            for k, v in node["inputs"].items()
        }
        title = TITLES.get(key) or (f"LoRA {key[4:]}" if key.startswith("lora") else None)
        out[ids[key]] = {**node, "inputs": inputs, **({"_meta": {"title": title}} if title else {})}
    return out


def _models(
    g: dict, loras: list[tuple[str, float]], attention: str, turbo: float = 1.0, unet: str = UNET
) -> list:
    """Loaders + turbo LoRA + user LoRAs + attention backend; returns the model link.
    turbo=0 leaves the turbo LoRA out, for models with turbo merged in (e.g. 10Eros TURBO)."""
    g["unet"] = _node("UNETLoader", unet_name=unet, weight_dtype="default")
    g["clip"] = _node("CLIPLoader", clip_name=TEXT_ENCODER, type="minimax", device="default")
    g["vae"] = _node("VAELoader", vae_name=VIDEO_VAE)
    g["audio_vae"] = _node("VAELoader", vae_name=AUDIO_VAE)
    model = ["unet", 0]
    stack = ([(TURBO_LORA, turbo)] if turbo else []) + list(loras)
    for i, (name, strength) in enumerate(stack, start=0 if turbo else 1):
        g[f"lora{i}"] = _node(
            "LoraLoaderModelOnly", lora_name=name, strength_model=strength, model=model
        )
        model = [f"lora{i}", 0]
    if attention:
        g["attention"] = _node("ModelAttentionBackend", attention=attention, model=model)
        model = ["attention", 0]
    return model


def _reference(
    g: dict, prompt: str, refs: list[str], width, height, seconds: float, ref_size: str = "match"
) -> None:
    for i, name in enumerate(refs):
        g[f"ref{i}"] = _node("LoadImage", image=name)
    g["seconds"] = _node("PrimitiveFloat", value=float(seconds))
    g["length"] = _node(
        "ComfyMathExpression", expression=LENGTH_EXPR, **{"values.a": ["seconds", 0]}
    )
    g["r2v"] = _node(
        "MiniMaxH3ReferenceToVideo",
        clip=["clip", 0],
        vae=["vae", 0],
        audio_vae=["audio_vae", 0],
        prompt=prompt,
        width=width,
        height=height,
        length=["length", 1],
        ref_image_size=ref_size,
        **{f"ref_images.ref_image_{i}": [f"ref{i}", 0] for i in range(len(refs))},
    )


def _sample(
    g: dict,
    model: list,
    positive: list,
    seed: int,
    steps: int,
    sampler: str = "res_multistep",
    scheduler: str = "simple",
) -> None:
    g["noise"] = _node("RandomNoise", noise_seed=int(seed))
    g["sampler"] = _node("KSamplerSelect", sampler_name=sampler)
    g["sigmas"] = _node(
        "BasicScheduler", scheduler=scheduler, steps=int(steps), denoise=1.0, model=model
    )
    g["guider"] = _node("BasicGuider", model=model, conditioning=positive)
    g["sample"] = _node(
        "SamplerCustomAdvanced",
        noise=["noise", 0],
        guider=["guider", 0],
        sampler=["sampler", 0],
        sigmas=["sigmas", 0],
        latent_image=["r2v", 1],
    )
    g["decode"] = _node("VAEDecode", samples=["sample", 0], vae=["vae", 0])
    g["decode_audio"] = _node("VAEDecodeAudio", samples=["sample", 0], vae=["audio_vae", 0])


def _save(g: dict, images: list, audio: list, prefix: str) -> None:
    g["video"] = _node("CreateVideo", images=images, audio=audio, fps=24.0)
    g["save"] = _node(
        "SaveVideo",
        video=["video", 0],
        filename_prefix=prefix,
        format="auto",
        **{"format.codec": "auto"},
        codec="auto",
    )


def clip(
    prompt: str,
    refs: list[str],
    *,
    seed: int = 1,
    width: int = 576,
    height: int = 1024,
    seconds: float = 5.0,
    steps: int = 4,
    loras: list[tuple[str, float]] = (),
    attention: str = "comfy kitchen attention",
    prefix: str = "AiAngel/h3",
    turbo: float = 1.0,
    sampler: str = "res_multistep",
    scheduler: str = "simple",
    unet: str = UNET,
    ref_size: str = "match",
) -> dict:
    g: dict = {}
    model = _models(g, list(loras), attention, turbo, unet)
    _reference(g, prompt, refs, width, height, seconds, ref_size)
    _sample(g, model, ["r2v", 0], seed, steps, sampler, scheduler)
    _save(g, ["decode", 0], ["decode_audio", 0], prefix)
    return _numbered(g)


def extend(
    prompt: str,
    refs: list[str],
    prev_video: str,
    *,
    seed: int = 1,
    seconds: float = 5.0,
    overlap: int = 22,
    steps: int = 4,
    loras: list[tuple[str, float]] = (),
    attention: str = "comfy kitchen attention",
    prefix: str = "AiAngel/h3-extend",
    turbo: float = 1.0,
    sampler: str = "res_multistep",
    scheduler: str = "simple",
    unet: str = UNET,
    ref_size: str = "match",
) -> dict:
    """New clip continuing `prev_video` (24 fps). `seconds` is the new segment incl. the overlap."""
    g: dict = {}
    model = _models(g, list(loras), attention, turbo, unet)
    g["prev"] = _node("LoadVideo", file=prev_video)
    g["parts"] = _node("GetVideoComponents", video=["prev", 0])
    g["size"] = _node("GetImageSize", image=["parts", 0])
    g["overlap"] = _node("PrimitiveInt", value=int(overlap))
    _reference(g, prompt, refs, ["size", 0], ["size", 1], seconds, ref_size)
    # previous clip: head (everything before the overlap) and tail (the overlap frames + audio)
    g["head_len"] = _node(
        "ComfyMathExpression",
        expression="a - b",
        **{"values.a": ["size", 2], "values.b": ["overlap", 0]},
    )
    g["prev_head"] = _node(
        "ImageFromBatch", image=["parts", 0], batch_index=0, length=["head_len", 1]
    )
    g["tail_start"] = _node("ComfyMathExpression", expression="-a", **{"values.a": ["overlap", 0]})
    g["prev_tail"] = _node(
        "ImageFromBatch", image=["parts", 0], batch_index=["tail_start", 1], length=["overlap", 0]
    )
    g["tail_secs"] = _node(
        "ComfyMathExpression", expression="a / 24", **{"values.a": ["overlap", 0]}
    )
    g["neg_tail_secs"] = _node(
        "ComfyMathExpression", expression="-(a / 24)", **{"values.a": ["overlap", 0]}
    )
    g["prev_tail_audio"] = _node(
        "TrimAudioDuration",
        audio=["parts", 1],
        start_index=["neg_tail_secs", 0],
        duration=["tail_secs", 0],
    )
    g["head_secs"] = _node(
        "ComfyMathExpression", expression="a / 24", **{"values.a": ["head_len", 1]}
    )
    g["prev_head_audio"] = _node(
        "TrimAudioDuration", audio=["parts", 1], start_index=0.0, duration=["head_secs", 0]
    )
    g["guide"] = _node(
        "MiniMaxH3AddGuide",
        positive=["r2v", 0],
        latent=["r2v", 1],
        frame_idx=0,
        vae=["vae", 0],
        audio_vae=["audio_vae", 0],
        image=["prev_tail", 0],
        audio=["prev_tail_audio", 0],
    )
    _sample(g, model, ["guide", 0], seed, steps, sampler, scheduler)
    # new segment: overlap part cross-faded with the previous tail, then the rest
    g["new_overlap"] = _node(
        "ImageFromBatch", image=["decode", 0], batch_index=0, length=["overlap", 0]
    )
    g["blend"] = _node(
        "ImageBlend",
        image1=["prev_tail", 0],
        image2=["new_overlap", 0],
        blend_factor=0.5,
        blend_mode="normal",
    )
    g["new_rest"] = _node(
        "ImageFromBatch", image=["decode", 0], batch_index=["overlap", 0], length=4096
    )
    g["join_a"] = _node("ImageBatch", image1=["prev_head", 0], image2=["blend", 0])
    g["join"] = _node("ImageBatch", image1=["join_a", 0], image2=["new_rest", 0])
    g["join_audio"] = _node(
        "AudioConcat", audio1=["prev_head_audio", 0], audio2=["decode_audio", 0], direction="after"
    )
    _save(g, ["join", 0], ["join_audio", 0], prefix)
    return _numbered(g)


if __name__ == "__main__":
    import json
    import sys
    from pathlib import Path

    out = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    out.mkdir(parents=True, exist_ok=True)
    for name, graph in (
        ("h3-clip", clip(EXAMPLE_PROMPT, ["example.png"])),
        ("h3-extend", extend(EXAMPLE_PROMPT, ["example.png"], "previous.mp4")),
    ):
        (out / f"{name}.api.json").write_text(json.dumps(graph, indent=1), encoding="utf-8")
        print(out / f"{name}.api.json")
