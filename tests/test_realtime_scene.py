"""Read-only capture and WebRTC image budget, without opening any devices."""
import base64
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from camera_capture_worker import CameraPair
from realtime_scene import encode_scene_image, MAX_JPEG_BYTES
from live_camera_session import LiveCameraSession


class SceneSnapshotTests(unittest.TestCase):
    def test_wrist_tool_image_rotates_clockwise_without_mutating_shared_frame(self):
        rgb = np.zeros((80, 120, 3), np.uint8)
        rgb[:40, :60] = [255, 0, 0]
        rgb[:40, 60:] = [0, 255, 0]
        rgb[40:, :60] = [0, 0, 255]
        rgb[40:, 60:] = [255, 255, 255]
        original = rgb.copy()
        result = encode_scene_image(rgb, 'wrist', 123.)
        self.assertEqual((result['width'], result['height']), (80, 120))
        self.assertEqual(result['capturedAt'], 123.)
        encoded = base64.b64decode(result['imageUrl'].split(',')[1])
        self.assertLessEqual(len(encoded), MAX_JPEG_BYTES)
        image = cv2.cvtColor(cv2.imdecode(np.frombuffer(encoded, np.uint8), cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
        # Distinct corners catch wrong direction, mirroring and a second rotation.
        for y, x, color in [(20, 20, [0, 0, 255]), (20, 60, [255, 0, 0]),
                            (100, 20, [255, 255, 255]), (100, 60, [0, 255, 0])]:
            np.testing.assert_allclose(image[y, x], color, atol=5)
        np.testing.assert_array_equal(rgb, original)
        overhead = encode_scene_image(rgb, 'overhead', 124.)
        self.assertEqual((overhead['width'], overhead['height']), (120, 80))

    def test_encoder_bounds_noise_payload_preserves_aspect_and_rgb(self):
        for rgb in (np.random.default_rng(42).integers(0, 256, (1080, 1440, 3), dtype=np.uint8),
                    np.full((720, 960, 3), [255, 0, 0], dtype=np.uint8)):
            result = encode_scene_image(rgb, 'overhead', 123.)
            encoded = base64.b64decode(result['imageUrl'].split(',')[1])
            self.assertLessEqual(len(encoded), MAX_JPEG_BYTES)
            image = cv2.imdecode(np.frombuffer(encoded, np.uint8), cv2.IMREAD_COLOR)
            self.assertEqual(image.shape[:2], (result['height'], result['width']))
            self.assertAlmostEqual(result['width'] / result['height'], 4 / 3, places=2)
            self.assertLessEqual(max(image.shape[:2]), 768)
            if rgb[0, 0, 0] == 255:
                self.assertGreater(int(image[0, 0, 2]), 240)
                self.assertLess(int(image[0, 0, 0]), 10)

    def test_conversation_reads_only_requested_observers_after_request(self):
        pair = CameraPair('conversation')
        rgb = np.full((720, 960, 3), 70, np.uint8)
        def fresh(**kw):
            self.assertGreaterEqual(time.monotonic(), kw['after'])
            self.assertTrue(kw['with_meta'])
            return rgb, time.monotonic()
        pair.observers = {role: Mock(snapshot=Mock(side_effect=fresh))
                          for role in ('cam0', 'cam1', 'wrist')}
        before = time.time()
        result = pair.scene_snapshot()
        self.assertEqual(result['status'], 'ok')
        self.assertEqual([(i['width'], i['height']) for i in result['images']], [(768, 576), (576, 768)])
        self.assertEqual(rgb.shape, (720, 960, 3))
        self.assertEqual([i['camera'] for i in result['images']], ['overhead', 'wrist'])
        self.assertTrue(all(before <= i['capturedAt'] <= time.time() for i in result['images']))
        pair.observers['cam1'].snapshot.assert_not_called()
        self.assertEqual(pair.observers['cam0'].snapshot.call_args.kwargs['after'],
                         pair.observers['wrist'].snapshot.call_args.kwargs['after'])

    def test_missing_overhead_never_substitutes_insta360(self):
        pair = CameraPair('molmoact2')
        pair.cameras = {'cam1': Mock()}
        pair.observers['wrist'] = Mock(snapshot=Mock(return_value=(np.full((720, 960, 3), 60, np.uint8), time.monotonic())))
        result = pair.scene_snapshot()
        self.assertEqual(result['status'], 'partial')
        self.assertEqual([i['camera'] for i in result['images']], ['wrist'])
        self.assertEqual(result['unavailable'][0]['camera'], 'overhead')
        pair.cameras['cam1'].read.assert_not_called()

    def test_physical_stream_waits_for_new_overhead_and_crops_without_policy_sync(self):
        pair = CameraPair('molmoact2')
        pair.cameras = {'cam0': Mock(), 'cam1': Mock()}
        pair.observers['wrist'] = Mock(snapshot=Mock(side_effect=RuntimeError('disconnected')))
        pair.latest['cam0'] = (np.full((720, 1280, 3), 20, np.uint8), time.monotonic() - 1)
        def produce():
            time.sleep(0.04)
            with pair.condition:
                pair.latest['cam0'] = (np.full((720, 1280, 3), 100, np.uint8), time.monotonic())
                pair.condition.notify_all()
        thread = threading.Thread(target=produce)
        thread.start()
        try:
            result = pair.scene_snapshot()
        finally:
            thread.join()
        self.assertEqual(result['status'], 'partial')
        image = result['images'][0]
        self.assertEqual(image['camera'], 'overhead')
        self.assertAlmostEqual(image['width'] / image['height'], 4 / 3)
        pair.cameras['cam0'].read.assert_not_called()
        pair.cameras['cam1'].read.assert_not_called()

    def test_failed_observers_report_both_missing_views(self):
        pair = CameraPair('conversation')
        result = pair.scene_snapshot()
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(result['images'], [])
        self.assertEqual(len(result['unavailable']), 2)

    def test_session_uses_existing_worker_and_never_starts_one(self):
        session = LiveCameraSession()
        with patch.object(session, '_start_locked') as start, patch.object(session, '_call', return_value={'images': []}) as rpc:
            with self.assertRaisesRegex(RuntimeError, 'not active'):
                session.scene_snapshot()
            session._process = Mock(poll=Mock(return_value=None))
            session._model_id = 'molmoact2'
            self.assertEqual(session.scene_snapshot(), {'images': []})
            rpc.assert_called_once_with('scene_snapshot')
            start.assert_not_called()
            session._process = None


if __name__ == '__main__':
    unittest.main()
