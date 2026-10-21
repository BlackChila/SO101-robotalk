#!/usr/bin/env python3
"""Download the pinned official Qwen3-ASR-1.7B checkpoint into this project."""

import hashlib
import json
from pathlib import Path

from huggingface_hub import snapshot_download


ROOT = Path(__file__).resolve().parents[1]
REPO = "Qwen/Qwen3-ASR-1.7B"
REVISION = "7278e1e70fe206f11671096ffdd38061171dd6e5"
DESTINATION = ROOT / "models" / "asr" / "qwen3-asr-1.7b"
FILES = (
    "chat_template.json",
    "config.json",
    "generation_config.json",
    "merges.txt",
    "model-00001-of-00002.safetensors",
    "model-00002-of-00002.safetensors",
    "model.safetensors.index.json",
    "preprocessor_config.json",
    "tokenizer_config.json",
    "vocab.json",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    snapshot_download(
        repo_id=REPO,
        revision=REVISION,
        local_dir=DESTINATION,
        allow_patterns=list(FILES),
        max_workers=3,
    )
    manifest = {
        "repo": REPO,
        "revision": REVISION,
        "files": {},
    }
    for name in FILES:
        path = DESTINATION / name
        if not path.is_file():
            raise RuntimeError(f"Missing checkpoint file: {path}")
        manifest["files"][name] = {"bytes": path.stat().st_size, "sha256": sha256(path)}
    manifest_path = ROOT / "environments" / "asr" / "model-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Verified {len(FILES)} files at revision {REVISION}")
    print(f"Manifest: {manifest_path}")


if __name__ == "__main__":
    main()
