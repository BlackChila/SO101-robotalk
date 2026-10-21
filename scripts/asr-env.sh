#!/usr/bin/env bash
# Source this file to select only the local Qwen3-ASR runtime.
ASR_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
export UV_CACHE_DIR="$ASR_ROOT/.cache/uv"
export HF_XET_CACHE="$ASR_ROOT/.cache/hf-xet"
export HF_HUB_DISABLE_TELEMETRY=1
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export TORCH_HOME="$ASR_ROOT/.cache/torch"
export TRITON_CACHE_DIR="$ASR_ROOT/.cache/triton-asr"
export TORCHINDUCTOR_CACHE_DIR="$ASR_ROOT/.cache/torchinductor-asr"
source "$ASR_ROOT/environments/asr/.venv/bin/activate"
