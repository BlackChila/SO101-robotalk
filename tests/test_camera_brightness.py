"""Native brightness controls and persistence without camera hardware."""
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import camera_brightness as brightness
import camera_capture_worker as worker

CONTROL = {"min": -64, "max": 64, "step": 1, "default": 0, "value": 0}


class CameraBrightnessTests(unittest.TestCase):
    def test_native_range_and_confirmation_and_unsupported_camera(self):
        with patch.object(brightness.subprocess, "run", return_value=SimpleNamespace(
            stdout="brightness 0x00980900 (int) : min=-256 max=256 step=1 default=0 value=12 flags=0x00001000")) as run:
            control = brightness.probe_brightness("/dev/x5")
            self.assertEqual(control["min"], -256)
            self.assertEqual(control["value"], 12)
            self.assertEqual(brightness.set_brightness("/dev/x5", 12, control), control)
            self.assertEqual(run.call_args_list[1].args[0][-2:], ["--set-ctrl", "brightness=12"])
            with self.assertRaises(RuntimeError):
                brightness.set_brightness("/dev/x5", 13, control)
        for stdout in ["", "brightness (int) : min=0 max=64 step=1 default=0 value=0 flags=inactive"]:
            with patch.object(brightness.subprocess, "run", return_value=SimpleNamespace(stdout=stdout)):
                self.assertIsNone(brightness.probe_brightness("/dev/camera"))

    def test_validation_and_settings_follow_device_across_profiles(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(brightness, "SETTINGS_PATH", Path(directory) / "settings.json"):
            for value in [True, 0.5, 65, -65, "12"]:
                with self.assertRaises(ValueError):
                    brightness.validate_brightness(value, CONTROL)
            brightness.save_brightness("/dev/overhead", 10)
            brightness.save_brightness("/dev/x5", -20)
            self.assertEqual(brightness.load_brightness(), {"/dev/overhead": 10, "/dev/x5": -20})

    def test_worker_saves_verified_setting_and_restores_hardware_after_failed_save(self):
        pair = worker.CameraPair("molmoact2")
        pair.cameras = {"cam0": object()}
        pair.brightness = {"cam0": CONTROL.copy()}
        with patch.object(worker, "probe_brightness", return_value=CONTROL.copy()), \
             patch.object(worker, "set_brightness", side_effect=lambda device, value, ctrl: {**ctrl, "value": value}) as write, \
             patch.object(pair, "preview", return_value={"cameraBrightness": {"cam0": {**CONTROL, "value": 12}}}) as preview, \
             patch.object(worker, "save_brightness") as save:
            result = pair.set_camera_brightness("cam0", 12)
            self.assertEqual(result["cameraBrightness"]["cam0"]["value"], 12)
            save.assert_called_once_with(pair.profile["cameras"]["cam0"]["path"], 12)
            self.assertGreater(preview.call_args.kwargs["after"], 0)
            save.side_effect = OSError("disk full")
            with self.assertRaisesRegex(OSError, "disk full"):
                pair.set_camera_brightness("cam0", 20)
            self.assertEqual(write.call_args.args[1], 0)
            self.assertEqual(pair.brightness["cam0"]["value"], 0)
            count = write.call_count
            with self.assertRaises(ValueError):
                pair.set_camera_brightness("cam0", 65)
            self.assertEqual(write.call_count, count)
            with self.assertRaises(RuntimeError):
                pair.set_camera_brightness("cam1", 10)

    def test_startup_reapplies_saved_values_to_actual_devices(self):
        pair = worker.CameraPair("molmoact2")
        pair.cameras = {"cam0": object(), "cam1": object()}
        device = pair.profile["cameras"]["cam0"]["path"]
        with patch.object(worker, "load_brightness", return_value={device: 10}), \
             patch.object(worker, "probe_brightness", return_value=CONTROL.copy()), \
             patch.object(worker, "set_brightness", return_value={**CONTROL, "value": 10}) as write:
            pair.initialize_brightness()
            write.assert_called_once_with(device, 10, CONTROL)
            self.assertEqual(pair.brightness_metadata()["cam0"]["value"], 10)
            self.assertEqual(pair.brightness_metadata()["cam1"]["value"], 0)


if __name__ == "__main__":
    unittest.main()
