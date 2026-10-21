# Piper TTS for local conversation

This isolated CPU environment powers the `Lokal · Piper` conversation mode.
It keeps Qwen3-ASR and LM Studio for transcription and reply generation. The
Qwen3-TTS path is shown as `Lokal · Qwen` and shares the same tool/vision
conversation controller; its live speech and physical acceptance still need
target-host validation. The maintainer reports Piper conversation
as working. With a locally hosted LM Studio model, speech, dialogue, and
MolmoAct2 manipulation run locally without an OpenAI API key.

From the repository root on the ARM64 host:

```bash
uv sync --project environments/piper --frozen --python /usr/bin/python3.12
environments/piper/.venv/bin/python -m piper.download_voices \
  --download-dir models/tts/piper \
  de_DE-thorsten-medium de_DE-kerstin-low \
  en_US-amy-medium en_US-ryan-medium \
  en_GB-alan-medium en_GB-jenny_dioco-medium
environments/piper/.venv/bin/python scripts/piper_tts_worker.py \
  --sample /tmp/so101-piper-sample.wav
```

Each voice has an `.onnx` and `.onnx.json` file under `models/tts/piper/`.
These downloads are separate from the package lock; no project-level pinned
voice manifest is currently supplied. Review each voice's upstream model card
and license before redistributing voice files or generated demo media.
The UI selects Thorsten (medium quality), Kerstin (low quality), or one of four
medium quality English voices: Amy and Ryan (US), Alan and Jenny (UK).
Select `Gesprächssprache` (`Deutsch` or `English`) before the call. The UI filters
the voice list to that language: Thorsten/Kerstin for German and
Amy/Ryan/Alan/Jenny for English. Voice changes apply on the next reply, including
announcements and task feedback. The worker caches each selected model and serves
successive requests through the same JSON-line interface as Qwen TTS. It does
not import robot control code. Its sample command generates audio only.

Voice sources: [Thorsten](https://huggingface.co/rhasspy/piper-voices/tree/main/de/de_DE/thorsten/medium),
[Kerstin](https://huggingface.co/rhasspy/piper-voices/tree/main/de/de_DE/kerstin/low),
[Amy](https://huggingface.co/rhasspy/piper-voices/tree/main/en/en_US/amy/medium),
[Ryan](https://huggingface.co/rhasspy/piper-voices/tree/main/en/en_US/ryan/medium),
[Alan](https://huggingface.co/rhasspy/piper-voices/tree/main/en/en_GB/alan/medium),
[Jenny](https://huggingface.co/rhasspy/piper-voices/tree/main/en/en_GB/jenny_dioco/medium).

The Piper robot conversation supports local tools, camera snapshots and face tracking.
See [local conversation workflow](../../docs/local-piper-conversation.md) for runtime
requirements, lifecycle and validation. Web search is not exposed in this mode.
