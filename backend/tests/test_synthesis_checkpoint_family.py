"""A local checkpoint's family comes from its safetensors header, not its file name.

Found 2026-09-12: an SDXL checkpoint with no "xl" in
its name was registered as SD 1.5, crashed inside StableDiffusionPipeline, and
every image silently fell back to stock SD 1.5.
"""

import json
import struct
from pathlib import Path

import pytest

from modules.synthesis import model_registry
from modules.synthesis.model_registry import SynthesisModelRegistry

pytestmark = pytest.mark.regression

SDXL_TENSORS = [
    "conditioner.embedders.0.transformer.text_model.embeddings.position_ids",
    "conditioner.embedders.1.model.ln_final.weight",
    "model.diffusion_model.input_blocks.0.0.weight",
]
SD15_TENSORS = [
    "cond_stage_model.transformer.text_model.embeddings.position_ids",
    "model.diffusion_model.input_blocks.0.0.weight",
]


def _write_safetensors(path: Path, tensor_names, metadata=None) -> Path:
    """A header-only safetensors file: enough to tell the family, no weights."""
    header = {name: {"dtype": "F16", "shape": [0], "data_offsets": [0, 0]} for name in tensor_names}
    if metadata:
        header["__metadata__"] = metadata
    raw = json.dumps(header).encode("utf-8")
    path.write_bytes(struct.pack("<Q", len(raw)) + raw)
    return path


def test_sdxl_weights_are_sdxl_whatever_the_file_is_called(tmp_path):
    path = _write_safetensors(tmp_path / "portraitMix_v30.safetensors", SDXL_TENSORS)

    assert model_registry._checkpoint_family(path) == "sdxl-checkpoint"


def test_sdxl_is_recognised_by_modelspec_metadata(tmp_path):
    path = _write_safetensors(
        tmp_path / "merged.safetensors",
        ["model.diffusion_model.out.0.weight"],
        {"modelspec.architecture": "stable-diffusion-xl-v1-base"},
    )

    assert model_registry._checkpoint_family(path) == "sdxl-checkpoint"


def test_sd15_weights_stay_sd15_even_with_xl_in_the_name(tmp_path):
    path = _write_safetensors(tmp_path / "pixel_xl_style.safetensors", SD15_TENSORS)

    assert model_registry._checkpoint_family(path) == "stable-diffusion-checkpoint"


@pytest.mark.parametrize(
    "name, expected",
    [
        ("juggernaut_xl.safetensors", "sdxl-checkpoint"),
        ("dreamshaper_8.safetensors", "stable-diffusion-checkpoint"),
        ("model_sdxl.ckpt", "sdxl-checkpoint"),
        ("model_v15.ckpt", "stable-diffusion-checkpoint"),
    ],
)
def test_without_a_readable_header_the_name_decides(tmp_path, name, expected):
    path = tmp_path / name
    path.write_bytes(b"not a safetensors header")

    assert model_registry._checkpoint_family(path) == expected


def test_registry_scan_gives_an_sdxl_checkpoint_sdxl_defaults(tmp_path, monkeypatch):
    _write_safetensors(tmp_path / "portraitMix_v30.safetensors", SDXL_TENSORS)
    monkeypatch.setattr(model_registry, "legacy_image_gen_diffuser_models_root", lambda: tmp_path / "missing-a")
    monkeypatch.setattr(model_registry, "legacy_image_generator_checkpoints_root", lambda: tmp_path / "missing-b")
    registry = SynthesisModelRegistry.__new__(SynthesisModelRegistry)  # no scan of the live storage
    registry._image_generator_root = tmp_path

    [model] = registry._scan_image_generator_checkpoints()

    assert model.family == "sdxl-checkpoint"
    assert (model.defaults["width"], model.defaults["height"]) == (1024, 1024)


def test_import_reads_the_header_unless_the_family_is_given(tmp_path):
    path = _write_safetensors(tmp_path / "portraitMix.safetensors", SDXL_TENSORS)

    assert SynthesisModelRegistry._infer_checkpoint_family(path, "auto") == "sdxl-checkpoint"
    assert SynthesisModelRegistry._infer_checkpoint_family(path, "sd15") == "stable-diffusion-checkpoint"
