#!/usr/bin/env python3
"""Install a complete demo intro take as the active, replaceable replay bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

from demo_intro_replay import ACTIVE_TAKE, load_take
from flux3_start_pose import FluxStartController


def copy_versioned(source: Path, directory: Path, stem: str) -> str:
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    destination = directory / f"{stem}-{digest[:16]}{source.suffix}"
    if destination.exists():
        if hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
            raise RuntimeError(f"Existing bundle file has the wrong content: {destination}")
        return destination.name
    with tempfile.NamedTemporaryFile(dir=directory, prefix=".install-", delete=False) as temporary:
        temporary_path = Path(temporary.name)
    try:
        shutil.copyfile(source, temporary_path)
        if hashlib.sha256(temporary_path.read_bytes()).hexdigest() != digest:
            raise RuntimeError(f"Bundle copy failed: {source}")
        os.replace(temporary_path, destination)
    finally:
        temporary_path.unlink(missing_ok=True)
    return destination.name


def install(source_take: Path) -> Path:
    controller = FluxStartController()  # Reads calibration only; no robot connection.
    take, samples = load_take(source_take, controller.bounds)
    directory = ACTIVE_TAKE.parent
    directory.mkdir(parents=True, exist_ok=True)
    audio_name = copy_versioned(Path(take["audio"]), directory, "audio")
    trajectory_name = copy_versioned(Path(take["trajectory"]), directory, "gesture")
    manifest = {key: take[key] for key in (
        "status", "audio_sha256", "audio_duration_s", "lead_in_s",
        "planned_duration_s", "target_fps", "calibration_sha256",
        "start_pose", "sample_count",
    )}
    manifest.update({"bundle_version": 1, "audio": audio_name,
                     "trajectory": trajectory_name})
    with tempfile.NamedTemporaryFile("w", dir=directory, prefix=".active-", delete=False) as temporary:
        temporary_path = Path(temporary.name)
        json.dump(manifest, temporary, ensure_ascii=False, indent=2, allow_nan=False)
        temporary.write("\n")
    try:
        # Switching the manifest last keeps the previous bundle usable until all
        # replacement files have been copied and checked.
        os.replace(temporary_path, ACTIVE_TAKE)
    finally:
        temporary_path.unlink(missing_ok=True)
    installed, installed_samples = load_take(ACTIVE_TAKE, controller.bounds)
    if len(installed_samples) != len(samples) or installed["audio_sha256"] != take["audio_sha256"]:
        raise RuntimeError("Active bundle validation failed")
    return ACTIVE_TAKE


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--take", type=Path, required=True,
                        help="Complete take report produced by demo_intro_capture.py")
    args = parser.parse_args()
    print(f"INTRO_ACTIVE_TAKE={install(args.take)}", flush=True)


if __name__ == "__main__":
    main()
