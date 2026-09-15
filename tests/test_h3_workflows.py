"""The H3 API graph builder (scripts/h3_workflows.py): wiring the pod runs depend on."""

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("h3_workflows", ROOT / "scripts" / "h3_workflows.py")
h3 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(h3)


def by_class(graph: dict, cls: str) -> list[dict]:
    return [n for n in graph.values() if n["class_type"] == cls]


def assert_links_resolve(graph: dict) -> None:
    for node in graph.values():
        for value in node["inputs"].values():
            if isinstance(value, list) and len(value) == 2 and isinstance(value[1], int):
                assert value[0] in graph, f"{node['class_type']} links to missing node {value[0]}"


def test_clip_defaults_use_turbo_lora_and_kitchen_attention():
    g = h3.clip(h3.EXAMPLE_PROMPT, ["a.png"])
    assert all(k.isdigit() for k in g)
    assert_links_resolve(g)
    loras = by_class(g, "LoraLoaderModelOnly")
    assert [n["inputs"]["lora_name"] for n in loras] == [h3.TURBO_LORA]
    assert (
        by_class(g, "ModelAttentionBackend")[0]["inputs"]["attention"] == "comfy kitchen attention"
    )
    assert by_class(g, "UNETLoader")[0]["inputs"]["unet_name"] == h3.UNET


def test_turbo_zero_drops_turbo_lora_for_merged_turbo_models():
    g = h3.clip(
        "p",
        ["a.png"],
        turbo=0,
        unet="eros.safetensors",
        loras=[("mystic.safetensors", 0.4)],
        sampler="euler",
        scheduler="beta",
        steps=6,
    )
    assert_links_resolve(g)
    assert [n["inputs"]["lora_name"] for n in by_class(g, "LoraLoaderModelOnly")] == [
        "mystic.safetensors"
    ]
    assert by_class(g, "UNETLoader")[0]["inputs"]["unet_name"] == "eros.safetensors"
    assert by_class(g, "KSamplerSelect")[0]["inputs"]["sampler_name"] == "euler"
    sched = by_class(g, "BasicScheduler")[0]["inputs"]
    assert (sched["scheduler"], sched["steps"]) == ("beta", 6)


def test_extend_anchors_tail_and_stitches_head_blend_rest():
    g = h3.extend("p", ["a.png"], "prev.mp4", overlap=22)
    assert_links_resolve(g)
    guide = by_class(g, "MiniMaxH3AddGuide")[0]["inputs"]
    assert guide["frame_idx"] == 0 and "image" in guide and "audio" in guide
    assert len(by_class(g, "ImageBatch")) == 2 and len(by_class(g, "ImageBlend")) == 1
    assert by_class(g, "AudioConcat")[0]["inputs"]["direction"] == "after"
    assert json.dumps(g)  # serialisable for POST /prompt


def node_id(graph: dict, node: dict) -> str:
    return next(k for k, v in graph.items() if v is node)


def test_clip_default_graph_has_no_upscale_nodes():
    g = h3.clip(h3.EXAMPLE_PROMPT, ["a.png"])
    assert_links_resolve(g)
    classes = [n["class_type"] for n in g.values()]
    assert classes.count("SamplerCustomAdvanced") == 1
    assert classes.count("VAEDecode") == 1
    assert classes.count("VAEDecodeAudio") == 1
    assert "MinimaxH3LatentUpscaler3D" not in classes
    save_images = by_class(g, "CreateVideo")[0]["inputs"]["images"]
    assert g[save_images[0]]["class_type"] == "VAEDecode"


def test_clip_upscale_inserts_upscaler_between_sample_and_decode():
    g = h3.clip(
        h3.EXAMPLE_PROMPT,
        ["a.png"],
        upscale=True,
        upscale_scale=2.5,
        upscale_model="foo_upscaler.safetensors",
    )
    assert_links_resolve(g)

    base_sample, refine_sample = by_class(g, "SamplerCustomAdvanced")
    base_id = node_id(g, base_sample)

    split = by_class(g, "LTXVSeparateAVLatent")[0]
    assert split["inputs"]["av_latent"] == [base_id, 1]
    split_id = node_id(g, split)

    up = by_class(g, "MinimaxH3LatentUpscaler3D")[0]
    assert up["inputs"]["latent"] == [split_id, 0]
    assert up["inputs"]["model_name"] == "foo_upscaler.safetensors"
    assert up["inputs"]["mode"] == "scale by multiplier"
    assert up["inputs"]["mode.scale"] == 2.5
    up_id = node_id(g, up)

    join = by_class(g, "LTXVConcatAVLatent")[0]
    assert join["inputs"]["video_latent"] == [up_id, 0]
    assert join["inputs"]["audio_latent"] == [split_id, 1]
    join_id = node_id(g, join)

    assert refine_sample["inputs"]["latent_image"] == [join_id, 0]
    assert refine_sample["inputs"]["guider"] == base_sample["inputs"]["guider"]
    assert refine_sample["inputs"]["noise"] == base_sample["inputs"]["noise"]
    assert refine_sample["inputs"]["sampler"] == base_sample["inputs"]["sampler"]

    sigmas_node = g[refine_sample["inputs"]["sigmas"][0]]
    assert sigmas_node["class_type"] == "ManualSigmas"
    assert sigmas_node["inputs"]["sigmas"] == h3.UPSCALE_REFINE_SIGMAS
    refine_id = node_id(g, refine_sample)

    save_images = by_class(g, "CreateVideo")[0]["inputs"]["images"]
    img_decode = g[save_images[0]]
    assert img_decode["class_type"] == "VAEDecode"
    assert img_decode["inputs"]["samples"] == [refine_id, 1]


def test_length_expression_lands_on_17k_plus_5_grid():
    for seconds in (2, 5, 8, 15):
        n = max(5, round(seconds * 24))
        frames = n + (5 - (n % 17)) % 17
        assert frames % 17 == 5 and frames >= seconds * 24
