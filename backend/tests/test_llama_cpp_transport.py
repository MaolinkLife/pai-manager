"""Unit tests for the llama.cpp transport layer.

Covers:
  * ``process.build_server_args`` — flag mapping, conditional flash-attn / mmap.
  * ``process._cuda_visible_devices_for`` — single-device scoping policy.
  * ``client._chat_payload`` / ``client._payload_shape`` — sampler passthrough.

No real HTTP traffic is made — those paths are exercised in the integration
tests for the generative provider in a later phase.
"""

from __future__ import annotations

import pytest

from modules.llama_cpp import client as llama_client
from modules.llama_cpp import process as llama_process


# ---------------------------------------------------------------------------
# process.build_server_args
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_build_server_args_minimal_model_only():
    args = llama_process.build_server_args(
        exe_path="/abs/llama-server.exe",
        host="127.0.0.1",
        port=8080,
        profile={"model_path": "/abs/model.gguf"},
    )
    assert args[0].endswith("llama-server.exe")
    assert "-m" in args
    assert "--host" in args and "--port" in args
    assert "--mmproj" not in args  # absent when mmproj_path is empty


@pytest.mark.regression
def test_build_server_args_flash_attn_true_normalizes_to_on():
    args = llama_process.build_server_args(
        exe_path="/abs/llama-server.exe",
        host="127.0.0.1",
        port=8080,
        profile={"model_path": "/abs/m.gguf", "flash_attn": True},
    )
    i = args.index("--flash-attn")
    assert args[i + 1] == "on"


@pytest.mark.regression
def test_build_server_args_flash_attn_string_kept_literal():
    args = llama_process.build_server_args(
        exe_path="/abs/llama-server.exe",
        host="127.0.0.1",
        port=8080,
        profile={"model_path": "/abs/m.gguf", "flash_attn": "auto"},
    )
    i = args.index("--flash-attn")
    assert args[i + 1] == "auto"


@pytest.mark.regression
def test_build_server_args_no_mmap_explicit():
    args = llama_process.build_server_args(
        exe_path="/abs/llama-server.exe",
        host="127.0.0.1",
        port=8080,
        profile={"model_path": "/abs/m.gguf", "no_mmap": True},
    )
    assert "--no-mmap" in args


@pytest.mark.regression
def test_build_server_args_mmap_false_also_emits_no_mmap():
    args = llama_process.build_server_args(
        exe_path="/abs/llama-server.exe",
        host="127.0.0.1",
        port=8080,
        profile={"model_path": "/abs/m.gguf", "mmap": False},
    )
    assert "--no-mmap" in args


@pytest.mark.regression
def test_build_server_args_unknown_flags_ignored():
    """Profile keys not in the allow-list must NOT leak onto the command line."""
    args = llama_process.build_server_args(
        exe_path="/abs/llama-server.exe",
        host="127.0.0.1",
        port=8080,
        profile={
            "model_path": "/abs/m.gguf",
            "no_op_offload": True,           # AI_WAIFU_Y had this, we don't.
            "swa_full": True,                # Same.
            "weird_custom_setting": "x",     # Arbitrary user noise.
        },
    )
    assert "--no-op-offload" not in args
    assert "--swa-full" not in args
    assert "weird_custom_setting" not in " ".join(args)


@pytest.mark.regression
def test_build_server_args_passes_sampler_values():
    args = llama_process.build_server_args(
        exe_path="/abs/llama-server.exe",
        host="127.0.0.1",
        port=8080,
        profile={
            "model_path": "/abs/m.gguf",
            "temperature": 0.7,
            "top_p": 0.9,
            "min_p": 0.05,
            "ctx_size": 8192,
            "n_gpu_layers": 99,
        },
    )
    joined = " ".join(args)
    assert "--temp 0.7" in joined
    assert "--top-p 0.9" in joined
    assert "--min-p 0.05" in joined
    assert "--ctx-size 8192" in joined
    assert "--n-gpu-layers 99" in joined


# ---------------------------------------------------------------------------
# CUDA scoping
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_cuda_visible_single_device_extracts_index():
    assert llama_process._cuda_visible_devices_for({"device": "CUDA1"}) == "1"
    assert llama_process._cuda_visible_devices_for({"device": "CUDA0"}) == "0"


@pytest.mark.regression
def test_cuda_visible_multi_device_returns_none():
    """Multi-GPU layouts must NOT be silently clipped to a single device."""
    assert llama_process._cuda_visible_devices_for({"device": "CUDA0,CUDA1"}) is None


@pytest.mark.regression
def test_cuda_visible_no_device_returns_none():
    assert llama_process._cuda_visible_devices_for({}) is None


# ---------------------------------------------------------------------------
# client payload helpers
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_chat_payload_streaming_flag_passthrough():
    payload = llama_client._chat_payload(
        messages=[{"role": "user", "content": "hi"}],
        stream=True,
        model="model.gguf",
        sampler=None,
    )
    assert payload["stream"] is True
    assert payload["model"] == "model.gguf"


@pytest.mark.regression
def test_chat_payload_sampler_filters_unknown_keys():
    payload = llama_client._chat_payload(
        messages=[{"role": "user", "content": "hi"}],
        stream=False,
        model=None,
        sampler={"temperature": 0.5, "unknown_param": "x"},
    )
    assert payload["temperature"] == 0.5
    assert "unknown_param" not in payload


@pytest.mark.regression
def test_payload_shape_summarises_messages_safely():
    shape = llama_client._payload_shape(
        {
            "messages": [
                {"role": "system", "content": "rules"},
                {"role": "user", "content": [{"type": "text", "text": "hi"}]},
            ],
            "model": "x",
            "stream": False,
        }
    )
    assert shape["message_count"] == 2
    assert shape["messages"][0]["content_kind"] == "str"
    assert shape["messages"][1]["content_kind"] == "list"
    assert shape["model"] == "x"
