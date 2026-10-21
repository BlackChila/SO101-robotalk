# Isolated Linux environments

Start with [the Linux installation guide](../docs/getting-started.md).
Each runtime has its own `.venv`; there is no shared root Python environment.
The `uv` projects target Linux ARM64. Do not mix packages between models or
regenerate their locks on macOS/Windows.

| Directory | Python / installation | Role and guide |
| --- | --- | --- |
| `asr/` | 3.12; `uv sync --frozen` | [Qwen3-ASR and the API backend](asr/README.md) |
| `robot/` | 3.12; pinned direct requirements | [Shared motor and camera workers](robot/README.md); no FLUX or Galaxea policies |
| `molmoact2/` | External reference environment; no independent lock here | [MolmoAct2 adapter and required local links](molmoact2/README.md) |
| `tts/` | 3.12; `uv sync --frozen` | [Qwen3-TTS CustomVoice](tts/README.md) |
| `piper/` | 3.12; `uv sync --frozen` | [CPU Piper TTS](piper/README.md) |
| `conversation/` | 3.12 legacy direct-model project | [LM Studio dialogue setup](conversation/README.md); the UI does not launch this project as its dialogue worker |

Locks/manifests describe selected packages and downloads. Committed validation
JSON describes prior reference-host checks, not this checkout's current readiness.
Model weights, source checkouts, environments, and external symlinks are ignored
and must be installed or recreated locally.

Policy-session workers calculate actions without commanding motors. The API can
hand validated action blocks to a separate physical controller after its gates
pass. Calling a UI task or a physical runner is different from a synthetic
compatibility check; read [the UI guide](../ui/README.md) and
[configuration](../docs/configuration.md) before hardware use.
