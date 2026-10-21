"""Read model-ready RGB frames from the UI's sole camera-owner process.

This transport never opens a video device or robot serial port. A physical
runner holds an exclusive lease for its whole run; the UI cannot switch camera
profiles or close the stream until that runner disconnects.
"""

from __future__ import annotations

import fcntl
import json
import socket
import struct
from contextlib import contextmanager
from pathlib import Path

import numpy as np

from camera_profiles import camera_profile

ROOT = Path(__file__).resolve().parents[1]
SOCKET_PATH = ROOT / "outputs/ui-camera-stream.sock"
LEASE_PATH = ROOT / "outputs/ui-camera-physical.lock"
MAX_HEADER = 65536
MAX_FRAME_BYTES = 32 * 1024 * 1024


class PhysicalCameraLeaseBusy(RuntimeError):
    pass


@contextmanager
def camera_switch_guard():
    """Hold the lease through a profile change, excluding physical clients."""
    LEASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LEASE_PATH.open("a+b") as lease:
        try:
            fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise PhysicalCameraLeaseBusy(
                "A physical run is using the cameras. Pause or end the run first."
            ) from exc
        try:
            yield
        finally:
            fcntl.flock(lease, fcntl.LOCK_UN)


def require_no_physical_client() -> None:
    with camera_switch_guard():
        pass


def _recv_exact(connection: socket.socket, count: int) -> bytes:
    parts = bytearray()
    while len(parts) < count:
        data = connection.recv(min(count - len(parts), 1024 * 1024))
        if not data:
            raise ConnectionError("The camera stream was closed.")
        parts.extend(data)
    return bytes(parts)


def receive_packet(connection: socket.socket) -> tuple[dict, bytes]:
    size = struct.unpack("!I", _recv_exact(connection, 4))[0]
    if not 0 < size <= MAX_HEADER:
        raise ValueError("Invalid camera packet header.")
    header = json.loads(_recv_exact(connection, size))
    count = int(header.get("payload_bytes", 0))
    if count < 0 or count > MAX_FRAME_BYTES:
        raise ValueError("Invalid camera packet size.")
    return header, _recv_exact(connection, count) if count else b""


def send_packet(connection: socket.socket, header: dict, payload: bytes = b"") -> None:
    if len(payload) > MAX_FRAME_BYTES:
        raise ValueError("Camera data is too large.")
    metadata = json.dumps({**header, "payload_bytes": len(payload)},
                          separators=(",", ":")).encode()
    if len(metadata) > MAX_HEADER:
        raise ValueError("The camera packet header is too large.")
    connection.sendall(struct.pack("!I", len(metadata)) + metadata + payload)


class SharedCameraClient:
    def __init__(self, model_id: str, *, socket_path: Path = SOCKET_PATH,
                 lease_path: Path = LEASE_PATH):
        self.model_id = model_id
        self.profile = camera_profile(model_id)
        self.socket_path = Path(socket_path)
        self.lease_path = Path(lease_path)
        self.connection: socket.socket | None = None
        self.lease = None
        self.last_timestamp = 0.0

    def connect(self) -> None:
        self.lease_path.parent.mkdir(parents=True, exist_ok=True)
        self.lease = self.lease_path.open("a+b")
        try:
            try:
                fcntl.flock(self.lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise PhysicalCameraLeaseBusy(
                    "The camera stream is in use by another controller or UI model run."
                ) from exc
            connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            connection.settimeout(2.0)
            connection.connect(str(self.socket_path))
            self.connection = connection
            send_packet(connection, {"op": "hello", "model": self.model_id,
                                     "version": self.profile["version"]})
            response, _ = receive_packet(connection)
            if (response.get("ok") is not True or response.get("model") != self.model_id
                    or response.get("version") != self.profile["version"]):
                raise RuntimeError(response.get("error", "Incorrect camera profile."))
        except BaseException:
            self.close()
            raise

    def fresh(self, *, timeout_s: float = 0.8) -> tuple[dict[str, np.ndarray], dict]:
        if self.connection is None:
            raise RuntimeError("The camera client is not connected.")
        self.connection.settimeout(timeout_s + 0.5)
        send_packet(self.connection, {"op": "frame", "after": self.last_timestamp,
                                      "timeout_s": timeout_s})
        header, payload = receive_packet(self.connection)
        if header.get("ok") is not True:
            raise RuntimeError(header.get("error", "No fresh camera image."))
        if header.get("model") != self.model_id or header.get("version") != self.profile["version"]:
            raise RuntimeError("The camera profile changed during the physical run.")
        roles = tuple(self.profile["cameras"])
        frames = {}
        offset = 0
        for role in roles:
            view = header.get("views", {}).get(role)
            if not isinstance(view, dict) or view.get("dtype") != "uint8":
                raise ValueError(f"Invalid camera image for {role}.")
            shape = tuple(view.get("shape", ()))
            if len(shape) != 3 or shape[2] != 3 or not all(isinstance(n, int) and n > 0 for n in shape):
                raise ValueError(f"Invalid image shape for {role}: {shape}")
            config = self.profile["cameras"][role]
            expected = (720, 960, 3) if role == "cam1" else (
                (config["crop"][3], config["crop"][2], 3)
                if config.get("crop") and self.profile["geometry"] != "existing"
                else (config["height"], config["width"], 3)
            )
            if shape != expected:
                raise ValueError(f"Incorrect image shape for {role}: {shape}; expected {expected}")
            count = int(np.prod(shape))
            if count > MAX_FRAME_BYTES or offset + count > len(payload):
                raise ValueError("Incomplete camera image.")
            frames[role] = np.frombuffer(payload[offset:offset + count], dtype=np.uint8).reshape(shape).copy()
            offset += count
        if offset != len(payload):
            raise ValueError("Excess camera data.")
        timestamp = float(header["timestamp"])
        if timestamp <= self.last_timestamp:
            raise RuntimeError("The camera did not provide a new image.")
        self.last_timestamp = timestamp
        return frames, header

    def close(self) -> None:
        if self.connection is not None:
            self.connection.close()
            self.connection = None
        if self.lease is not None:
            fcntl.flock(self.lease, fcntl.LOCK_UN)
            self.lease.close()
            self.lease = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *_):
        self.close()
