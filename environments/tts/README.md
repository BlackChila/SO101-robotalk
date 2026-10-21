# Qwen3-TTS CustomVoice

This isolated Linux ARM64 / Python 3.12 environment supplies speech for
`Conversation → Local · Qwen`. The worker uses CUDA; Piper is a separate CPU
alternative. Local dialogue also requires ASR and an LM Studio API server.

The UI now uses Piper's shared local conversation controller for Qwen speech,
including MolmoAct2 tools, reset, camera images and task feedback. Software tests
use mocked models/controllers; live speech and physical task acceptance remain
unverified. See [the shared protocol](../../docs/local-piper-conversation.md).

From the repository root on the reference Linux system:

```bash
UV_CACHE_DIR="$PWD/.cache/uv" uv sync --project environments/tts --frozen --python /usr/bin/python3.12
HF_HUB_OFFLINE=0 TRANSFORMERS_OFFLINE=0 HF_HUB_DISABLE_TELEMETRY=1 \
  HF_XET_CACHE="$PWD/.cache/hf-xet" \
  environments/tts/.venv/bin/python scripts/download_tts.py
```

The script downloads
[Qwen3-TTS-12Hz-1.7B-CustomVoice](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice)
to `models/tts/qwen3-tts-1.7b-customvoice/` (~4.52 GB in the committed manifest).
It reuses the revision in `model-manifest.json` and records SHA-256 hashes of the
downloaded files. Keep that manifest when reproducing the reference download.

To generate a WAV without robot motion:

```bash
environments/tts/.venv/bin/python scripts/tts_worker.py --sample /tmp/robotalk-qwen-sample.wav
```

The sample uses speaker Ryan and German text; it writes audio and does not play
it or command motors. The UI offers nine CustomVoice speakers and defaults to
Dylan. The UI's `Conversation language` selection controls German or English synthesis
for the call, independently of the speaker choice. It is not a voice
cloning or VoiceDesign workflow.

The API starts this worker in its own process and reuses it across replies. Use
[the speech guide](../../docs/speech-interface.md) for conversation behavior and
[the LM Studio guide](../conversation/README.md) for dialogue setup. Original-host
voice checks do not substitute for listening and latency checks on a new setup.

Source: [official Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS).
Model/voice terms apply independently; review them before distributing generated
demo assets or offering a service.
