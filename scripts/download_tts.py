#!/usr/bin/env python3
"""Download the official CustomVoice checkpoint and record the exact revision."""

import hashlib
import json
from pathlib import Path

from huggingface_hub import HfApi, snapshot_download


ROOT = Path(__file__).resolve().parents[1]
REPO = "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"
DESTINATION = ROOT / "models" / "tts" / "qwen3-tts-1.7b-customvoice"
MANIFEST = ROOT / "environments" / "tts" / "model-manifest.json"


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def main() -> None:
    revision = json.loads(MANIFEST.read_text())["revision"] if MANIFEST.is_file() else HfApi().model_info(REPO).sha
    snapshot_download(repo_id=REPO, revision=revision, local_dir=DESTINATION, max_workers=3)
    files = {}
    for path in sorted(DESTINATION.rglob("*")):
        if path.is_file() and ".cache" not in path.parts:
            files[str(path.relative_to(DESTINATION))] = {"bytes": path.stat().st_size, "sha256": digest(path)}
    if not any(name.endswith(".safetensors") for name in files):
        raise RuntimeError("TTS checkpoint weights are missing")
    MANIFEST.write_text(json.dumps({"repo": REPO, "revision": revision, "files": files}, indent=2) + "\n")
    print(f"Verified {len(files)} files at {revision}")


if __name__ == "__main__":
    main()
