"""Exercise the local UI-to-physical frame transport without camera hardware."""

import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from camera_capture_worker import PhysicalFrameServer
from camera_profiles import camera_profile
from shared_camera_stream import (PhysicalCameraLeaseBusy, SharedCameraClient,
                                  camera_switch_guard, require_no_physical_client)
import shared_camera_stream


class FakePair:
    model_id = "molmoact2"
    profile = camera_profile(model_id)

    def camera_sources(self):
        return {"cam0": "cam0", "cam1": "cam1"}

    def read_views(self, *, after=0, with_meta=False, timeout_s=0.8):
        stamp = time.monotonic()
        frames = {
            "cam0": np.full((720, 960, 3), 12, np.uint8),
            "cam1": np.full((720, 960, 3), 34, np.uint8),
        }
        stamps = {"cam0": stamp, "cam1": stamp}
        return (frames, stamps) if with_meta else frames


class FakeSingleMolmoPair:
    model_id = "molmoact2"
    profile = camera_profile(model_id)

    def camera_sources(self):
        return {"cam0": "cam0", "cam1": "cam0"}

    def read_views(self, *, after=0, with_meta=False, timeout_s=0.8):
        stamp = time.monotonic()
        overhead = np.full((720, 960, 3), 37, np.uint8)
        frames = {"cam0": overhead, "cam1": overhead.copy()}
        stamps = {"cam0": stamp, "cam1": stamp}
        return (frames, stamps) if with_meta else frames


class SharedCameraStreamTests(unittest.TestCase):
    def test_physical_client_receives_profiled_rgb_and_blocks_switch(self):
        with tempfile.TemporaryDirectory() as directory:
            socket_path = Path(directory) / "camera.sock"
            lease_path = Path(directory) / "lease.lock"
            server = PhysicalFrameServer(FakePair(), socket_path)
            server.start()
            try:
                with patch.object(shared_camera_stream, "LEASE_PATH", lease_path):
                    with SharedCameraClient("molmoact2", socket_path=socket_path,
                                            lease_path=lease_path) as client:
                        frames, header = client.fresh()
                        self.assertEqual(frames["cam0"].shape, (720, 960, 3))
                        self.assertEqual(frames["cam1"].shape, (720, 960, 3))
                        self.assertEqual(int(frames["cam0"][0, 0, 0]), 12)
                        self.assertEqual(header["model"], "molmoact2")
                        self.assertGreater(client.fresh()[1]["timestamp"], header["timestamp"])
                        with self.assertRaises(PhysicalCameraLeaseBusy):
                            require_no_physical_client()
                    with camera_switch_guard():
                        pass
            finally:
                server.close()

    def test_wrong_model_is_rejected_before_frames(self):
        with tempfile.TemporaryDirectory() as directory:
            socket_path = Path(directory) / "camera.sock"
            server = PhysicalFrameServer(FakePair(), socket_path)
            server.start()
            try:
                with self.assertRaisesRegex(RuntimeError, "Kameraprofil passt nicht"):
                    SharedCameraClient("conversation", socket_path=socket_path,
                                       lease_path=Path(directory) / "lease.lock").connect()
            finally:
                server.close()

    def test_single_molmo_camera_keeps_two_fresh_model_slots(self):
        with tempfile.TemporaryDirectory() as directory:
            socket_path = Path(directory) / "camera.sock"
            lease_path = Path(directory) / "lease.lock"
            server = PhysicalFrameServer(FakeSingleMolmoPair(), socket_path)
            server.start()
            try:
                with SharedCameraClient("molmoact2", socket_path=socket_path,
                                        lease_path=lease_path) as client:
                    frames, header = client.fresh()
                    np.testing.assert_array_equal(frames["cam0"], frames["cam1"])
                    self.assertEqual(header["camera_sources"], {"cam0": "cam0", "cam1": "cam0"})
                    self.assertGreater(client.fresh()[1]["timestamp"], header["timestamp"])
            finally:
                server.close()


if __name__ == "__main__":
    unittest.main()
