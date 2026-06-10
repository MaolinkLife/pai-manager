"""Launcher for the ``llama-server`` executable.

The AI_WAIFU_Y original maps ~80 server flags. We deliberately keep only the
subset that actually matters for pai-manager's deployment model. If a future
feature needs another flag, add it to ``_VALUE_FLAGS`` / ``_BOOL_FLAGS`` —
do not pass through arbitrary args without thinking about the surface area.
"""

from __future__ import annotations

import os
import subprocess
from typing import Any

from modules.llama_cpp.models import project_path


# Flags that take a value: profile_key -> CLI flag.
_VALUE_FLAGS: dict[str, str] = {
    "alias": "--alias",
    "ctx_size": "--ctx-size",
    "batch_size": "--batch-size",
    "ubatch_size": "--ubatch-size",
    "threads": "--threads",
    "parallel": "--parallel",
    "n_gpu_layers": "--n-gpu-layers",
    "main_gpu": "--main-gpu",
    "device": "--device",
    "tensor_split": "--tensor-split",
    "split_mode": "--split-mode",
    "cache_type_k": "--cache-type-k",
    "cache_type_v": "--cache-type-v",
    "chat_template": "--chat-template",
    "temperature": "--temp",
    "top_k": "--top-k",
    "top_p": "--top-p",
    "min_p": "--min-p",
    "repeat_penalty": "--repeat-penalty",
    "seed": "--seed",
    "api_key": "--api-key",
}

# Boolean flags: presence-only.
_BOOL_FLAGS: dict[str, str] = {
    "cont_batching": "--cont-batching",
    "mlock": "--mlock",
    "jinja": "--jinja",
    "metrics": "--metrics",
    "no_warmup": "--no-warmup",
}


def _add_value(args: list[str], profile: dict[str, Any], key: str, flag: str) -> None:
    value = profile.get(key)
    if value not in (None, ""):
        args += [flag, str(value)]


def _add_bool(args: list[str], profile: dict[str, Any], key: str, flag: str) -> None:
    if profile.get(key) is True:
        args.append(flag)


def build_server_args(*, exe_path: str, host: str, port: int, profile: dict[str, Any]) -> list[str]:
    """Materialise CLI args for ``llama-server`` given a profile dict."""
    args = [project_path(exe_path)]

    model_path = project_path(str(profile.get("model_path") or ""))
    if model_path:
        args += ["-m", model_path]

    mmproj_path = project_path(str(profile.get("mmproj_path") or ""))
    if mmproj_path:
        args += ["--mmproj", mmproj_path]

    args += ["--host", str(profile.get("host") or host), "--port", str(int(profile.get("port") or port))]

    for key, flag in _VALUE_FLAGS.items():
        _add_value(args, profile, key, flag)

    for key, flag in _BOOL_FLAGS.items():
        _add_bool(args, profile, key, flag)

    # Flash-attention has three valid values: True (→ "on"), "on", "off", "auto".
    flash_attn = profile.get("flash_attn")
    if flash_attn in (True, "on", "off", "auto"):
        args += ["--flash-attn", "on" if flash_attn is True else str(flash_attn)]

    if profile.get("no_mmap") is True or profile.get("mmap") is False:
        args.append("--no-mmap")

    if bool(profile.get("embedding")):
        args.append("--embedding")

    if bool(profile.get("reranking")):
        args.append("--reranking")

    return args


def _cuda_visible_devices_for(profile: dict[str, Any]) -> str | None:
    """If exactly one CUDA device was requested via "CUDAn", scope CUDA_VISIBLE_DEVICES.

    Multi-GPU profiles fall through (None) — they need ``tensor_split`` / ``device``
    to express their layout and we don't want to clip them to a single device.
    """
    device = str(profile.get("device") or "").strip()
    if not device:
        return None
    parts = [part.strip() for part in device.split(",") if part.strip()]
    if len(parts) != 1:
        return None
    part = parts[0]
    upper = part.upper()
    index = upper[4:].strip() if upper.startswith("CUDA") else part.strip()
    return index if index.isdigit() else None


def _normalize_single_gpu_profile(profile: dict[str, Any]) -> dict[str, Any]:
    """When scoping to a single CUDA device, we expose it as CUDA0 inside the child process."""
    visible = _cuda_visible_devices_for(profile)
    if visible is None:
        return profile
    normalized = dict(profile)
    normalized["device"] = "CUDA0"
    normalized["main_gpu"] = 0
    return normalized


def start_server_process(
    *,
    exe_path: str,
    host: str,
    port: int,
    profile: dict[str, Any],
    log_dir: str,
    profile_name: str,
) -> subprocess.Popen:
    """Spawn ``llama-server`` with stdout/stderr piped into ``log_dir``."""
    process_profile = _normalize_single_gpu_profile(profile)
    args = build_server_args(exe_path=exe_path, host=host, port=port, profile=process_profile)

    workdir = os.path.dirname(args[0]) or None
    os.makedirs(project_path(log_dir), exist_ok=True)
    stdout_path = os.path.join(project_path(log_dir), f"{profile_name}.out.log")
    stderr_path = os.path.join(project_path(log_dir), f"{profile_name}.err.log")
    stdout = open(stdout_path, "a", encoding="utf-8", errors="replace")
    stderr = open(stderr_path, "a", encoding="utf-8", errors="replace")

    env = os.environ.copy()
    visible_devices = _cuda_visible_devices_for(profile)
    if visible_devices is not None:
        env["CUDA_VISIBLE_DEVICES"] = visible_devices

    creationflags = 0
    if os.name == "nt":
        # Matches run.py: lets us deliver CTRL_BREAK to shut the child down cleanly.
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

    return subprocess.Popen(
        args,
        cwd=workdir,
        stdout=stdout,
        stderr=stderr,
        env=env,
        creationflags=creationflags,
    )
