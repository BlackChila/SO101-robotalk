"""CPU-only face stream checks; no camera or robot devices are opened."""
import io
import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import camera_capture_worker as camera_worker
from camera_observer import OptionalCameraObserver
from face_detection import FaceAssociation, FaceDetectionWorker, upright_frame
from live_camera_session import LiveCameraSession
from download_face_detector import download_model, verify_model


def face(x, y, width=20, height=20, score=0.95):
    return np.array([x, y, width, height] + [0] * 10 + [score], dtype=np.float32)


class FaceDetectionTests(unittest.TestCase):
    def test_upright_rotation_and_bgr_conversion_do_not_mutate_source(self):
        rgb = np.zeros((2, 3, 3), np.uint8)
        rgb[0, 0] = [255, 0, 0]
        original = rgb.copy()
        actual = upright_frame(rgb)
        self.assertEqual(actual.shape, (3, 2, 3))
        np.testing.assert_array_equal(actual[0, 1], [0, 0, 255])
        np.testing.assert_array_equal(original, rgb)
        self.assertEqual(upright_frame(np.zeros((1080, 1920, 3), np.uint8)).shape, (640, 360, 3))

    def test_association_stays_with_face_and_delays_bystander_switch(self):
        association = FaceAssociation(retention_s=1)
        first = association.select([face(10, 10), face(70, 70, score=0.85)], 100, 100, 1)
        second = association.select([face(12, 10, score=0.8), face(70, 70, score=0.99)], 100, 100, 1.1)
        self.assertLess(first["box"][0], 0.2)
        self.assertLess(second["box"][0], 0.2)
        self.assertIsNone(association.select([face(70, 70)], 100, 100, 1.3))
        self.assertGreater(association.select([face(70, 70)], 100, 100, 2.2)["box"][0], 0.6)

    def test_invalid_detections_are_ignored(self):
        association = FaceAssociation()
        invalid = face(0, 0)
        invalid[0] = float("nan")
        self.assertIsNone(association.select([invalid, face(0, 0, width=-1), face(200, 200)], 100, 100, 1))

    def test_observer_metadata_preserves_capture_time_and_returns_copy(self):
        observer = OptionalCameraObserver({"width": 4, "height": 3})
        observer.camera, observer.error = object(), None
        captured_at = time.monotonic() - 0.05
        source = np.zeros((3, 4, 3), np.uint8)
        observer.latest = (source, captured_at)
        image, stamp = observer.snapshot(raw=True, with_meta=True)
        self.assertEqual(stamp, captured_at)
        image[:] = 255
        self.assertEqual(source.sum(), 0)

    def test_thread_preserves_capture_timestamp_and_stops_cleanly(self):
        captured_at = time.monotonic() - 0.05
        observer = Mock(available=True)
        delivered = threading.Event()
        def snapshot(**kwargs):
            if kwargs["after"] == 0:
                return np.zeros((80, 100, 3), np.uint8), captured_at
            delivered.set()
            worker._stop.wait(0.3)
            raise TimeoutError("camera stalled")
        observer.snapshot.side_effect = snapshot
        detector = Mock()
        detector.detect.return_value = (1, np.array([face(10, 20)]))
        worker = FaceDetectionWorker(observer)
        with patch.object(worker, "_availability_error", return_value=None), \
             patch("face_detection.verify_model"), \
             patch("face_detection.cv2.FaceDetectorYN.create", return_value=detector):
            worker.start()
            self.assertTrue(delivered.wait(1))
            result = worker.status()
            self.assertEqual(result["observation"]["captured_at"], captured_at)
            self.assertTrue(result["observation"]["detected"])
            self.assertAlmostEqual(result["observation"]["x"], 20 / 80)
            self.assertEqual(result["preview"]["height"], 100)
            stopped = worker.stop()
            self.assertFalse(stopped["running"])
            self.assertIsNone(stopped["observation"])

    def test_stale_frames_fault_instead_of_publishing_new_observations(self):
        worker = FaceDetectionWorker(Mock(available=True))
        worker.observer.snapshot.return_value = (np.zeros((3, 4, 3), np.uint8), time.monotonic() - 2)
        worker._detector = Mock()
        worker._run()
        result = worker.status()
        self.assertEqual(result["state"], "fault")
        self.assertIn("Stale", result["error"])
        self.assertIsNone(result["observation"])
        worker._detector.detect.assert_not_called()

    def test_missing_model_gives_explicit_install_command_without_download(self):
        with tempfile.TemporaryDirectory() as directory, patch("urllib.request.urlopen") as request:
            worker = FaceDetectionWorker(Mock(available=True), Path(directory) / "missing.onnx")
            with self.assertRaisesRegex(RuntimeError, "download_face_detector.py"):
                worker.start()
            request.assert_not_called()

    def test_downloader_rejects_bad_payload_and_preserves_existing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "model.onnx"
            destination.write_bytes(b"old")
            with patch("urllib.request.urlopen", return_value=io.BytesIO(b"bad")):
                with self.assertRaisesRegex(ValueError, "checksum"):
                    download_model(destination)
            self.assertEqual(destination.read_bytes(), b"old")
            with self.assertRaises(ValueError):
                verify_model(destination)

    def test_camera_pair_uses_existing_observer_and_refuses_policy_wrist_profiles(self):
        pair = camera_worker.CameraPair("conversation")
        with patch.object(camera_worker, "FaceDetectionWorker") as detector:
            pair.face_tracking("start")
            detector.assert_called_once_with(pair.observers["wrist"])
            detector.return_value.start.assert_called_once()
            pair.face_tracking("stop")
            detector.return_value.stop.assert_called_once()
        with self.assertRaises(ValueError):
            camera_worker.CameraPair("flux3").face_tracking("start")

    def test_rpc_routes_action_without_camera_read_or_motor_access(self):
        output = io.StringIO()
        with patch.object(camera_worker, "CameraPair") as pair, \
             patch.object(camera_worker, "PhysicalFrameServer"), \
             patch.object(camera_worker.sys, "stdout", output), \
             patch.object(camera_worker.sys, "stdin", io.StringIO('{"op":"face_tracking","action":"start"}\n{"op":"stop"}\n')):
            pair.return_value.face_tracking.return_value = {"running": True}
            camera_worker.serve("conversation")
        pair.return_value.face_tracking.assert_called_once_with("start")
        self.assertTrue(json.loads(output.getvalue().splitlines()[1].split(":", 1)[1])["running"])

    def test_session_serializes_rpc_and_requires_appropriate_profile(self):
        session = LiveCameraSession()
        session._process = Mock()
        session._process.poll.return_value = None
        session._model_id = "conversation"
        with patch.object(session, "_call", return_value={"running": True}) as call:
            self.assertTrue(session.face_tracking("start")["running"])
            call.assert_called_once_with("face_tracking", action="start", timeout_s=5)
            session._model_id = "flux3"
            with self.assertRaises(RuntimeError):
                session.face_tracking("start")


if __name__ == "__main__":
    unittest.main()
