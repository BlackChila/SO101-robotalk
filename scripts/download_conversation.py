#!/usr/bin/env python3
"""Download the ggml-org Qwen3.8-27B Q4_K_M GGUF and verify its checksum."""

import hashlib
import json
from pathlib import Path

from huggingface_hub import HfApi, hf_hub_download


ROOT = Path(__file__).resolve().parents[1]
REPO = "ggml-org/Qwen3.8-27B-GGUF"
FILENAME = "Qwen3.8-27B-Q4_K_M.gguf"
DESTINATION = ROOT / "models" / "conversation" / "qwen3.8-27b-q4_k_m"
MANIFEST = ROOT / "environments" / "conversation" / "model-manifest.json"


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def main() -> None:
    revision = json.loads(MANIFEST.read_text())["revision"] if MANIFEST.is_file() else HfApi().model_info(REPO).sha
    path = Path(hf_hub_download(repo_id=REPO, filename=FILENAME,
                                revision=revision, local_dir=DESTINATION))
    if not path.is_file() or path.stat().st_size < 10_000_000_000:
        raise RuntimeError("Q4_K_M GGUF checkpoint is incomplete")
    MANIFEST.write_text(json.dumps({"repo": REPO, "revision": revision,
        "file": FILENAME, "bytes": path.stat().st_size, "sha256": digest(path)}, indent=2) + "\n")
    print(f"Verified {path.stat().st_size} bytes at {revision}")


if __name__ == "__main__":
    main()
