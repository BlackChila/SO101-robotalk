# Dialogue through LM Studio

The current UI uses an independently installed LM Studio server for both local
conversation modes. It does **not** launch a Transformers worker from this
directory. The `pyproject.toml` and `uv.lock` here describe an earlier direct-model
environment; installing that project is not required for LM Studio dialogue.

Both local modes now share the tool/vision dialogue path. Qwen uses the same
bounded backend history and tool dispatch as Piper, with a different speech
worker. Qwen live speech and physical behavior still require target-host checks.

## Set up local dialogue on Linux

1. Install [LM Studio](https://lmstudio.ai/download) on the target Linux host.
2. Install and load your chosen dialogue model in LM Studio. The reference
   setup used `qwen/qwen3.8-27b` in `Q4_K_M` quantization.
3. Enable the LM Studio API server. Confirm its address and model key, then export
   them before starting RoboTalk:

```bash
export SO101_LM_STUDIO_URL=http://127.0.0.1:1234
export SO101_CONVERSATION_MODEL=qwen/qwen3.8-27b
```

The code defaults to `http://172.17.0.1:1234` on the original host. The localhost
example applies only when your server actually listens there. If its server
requires authentication, export `SO101_LM_STUDIO_TOKEN` locally. These settings
are read from the process environment, not the root `.env` parser.

Both modes use LM Studio's native `/api/v1/models` and `/api/v1/models/load`
for model readiness/loading, and `/v1/chat/completions` for dialogue, structured
function calls and scene images. The selected model/runtime must support tools
and `image_url` inputs for those features. A text-only model cannot describe scenes.
The legacy stateful `/api/v1/chat` backend routes remain for older clients; the
current UI uses the shared tool protocol for both local modes.

Test the selected model's behavior before physical tasks. An installed model
name or a mocked protocol test does not establish reliable vision/tool behavior.

## Optional GGUF download helper

You can use LM Studio's own model download/import workflow. Alternatively, once
the ASR environment is installed, the repository's helper can download the GGUF
using its Hugging Face dependency:

```bash
HF_HUB_OFFLINE=0 TRANSFORMERS_OFFLINE=0 \
  environments/asr/.venv/bin/python scripts/download_conversation.py
```

The helper targets [ggml-org/Qwen3.8-27B-GGUF](https://huggingface.co/ggml-org/Qwen3.8-27B-GGUF),
file `Qwen3.8-27B-Q4_K_M.gguf`, under
`models/conversation/qwen3.8-27b-q4_k_m/`. It records a revision and checksum in
`environments/conversation/model-manifest.json`. **No such manifest is currently
committed**, so a fresh download resolves the current upstream revision. The
computed hash is a record, not a comparison with an independently supplied
expected hash. Retain/review the resulting manifest for reproducibility.

A downloaded GGUF is not automatically installed in LM Studio. Import it using
[LM Studio's import workflow](https://lmstudio.ai/docs/cli/local-models/import),
then verify the actual server model key. If using `lms import`, choose the copy or
link option deliberately: the CLI moves the original file by default.

Install [Qwen TTS](../tts/README.md) or [Piper](../piper/README.md) separately.
See [current speech behavior](../../docs/speech-interface.md) and
[the shared local tool protocol](../../docs/local-piper-conversation.md).
