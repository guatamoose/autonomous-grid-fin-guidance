import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from servo_controller import (expected_settings, load_airframe_profile,
                              pulses_for)


class AirframeProfileTests(unittest.TestCase):
    def setUp(self):
        self.profile = load_airframe_profile(
            ROOT / "deploy" / "airframes" / "rocket-02.json")

    def test_rocket_02_calibration_and_positions(self):
        self.assertEqual(self.profile.name, "rocket-02")
        self.assertEqual(self.profile.neutral, {
            7: 1525, 8: 1340, 9: 1715, 10: 1275,
        })
        self.assertEqual(
            {position: fin.channel
             for position, fin in self.profile.fins.items()},
            {"top": 7, "right": 8, "bottom": 9, "left": 10})
        self.assertEqual(expected_settings(self.profile), {
            7: {"function": 0, "min": 1125, "max": 1925,
                "trim": 1525},
            8: {"function": 0, "min": 940, "max": 1740,
                "trim": 1340},
            9: {"function": 0, "min": 1315, "max": 2115,
                "trim": 1715},
            10: {"function": 0, "min": 875, "max": 1675,
                 "trim": 1275},
        })

    def test_horizontal_pair_tilts_together_with_mirrored_pwm(self):
        decision = SimpleNamespace(safe_nose_x_us=200,
                                   safe_nose_y_us=0)
        pulses = pulses_for(decision, self.profile)
        self.assertEqual(pulses, {
            7: 1325, 8: 1340, 9: 1915, 10: 1275,
        })

    def test_vertical_pair_tilts_together_with_mirrored_pwm(self):
        decision = SimpleNamespace(safe_nose_x_us=0,
                                   safe_nose_y_us=-200)
        pulses = pulses_for(decision, self.profile)
        self.assertEqual(pulses, {
            7: 1525, 8: 1140, 9: 1715, 10: 1475,
        })

    def test_full_400_offset_reaches_saved_endpoints(self):
        decision = SimpleNamespace(safe_nose_x_us=-400,
                                   safe_nose_y_us=400)
        self.assertEqual(pulses_for(decision, self.profile), {
            7: 1925, 8: 1740, 9: 1315, 10: 875,
        })

    def test_duplicate_channel_is_rejected(self):
        data = json.loads(
            (ROOT / "deploy" / "airframes" / "rocket-02.json")
            .read_text(encoding="utf-8"))
        data["fins"]["left"]["channel"] = 8
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unique"):
                load_airframe_profile(path)

    def test_range_without_400_each_way_is_rejected(self):
        data = json.loads(
            (ROOT / "deploy" / "airframes" / "rocket-02.json")
            .read_text(encoding="utf-8"))
        data["fins"]["top"]["minimum"] = 1200
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "400"):
                load_airframe_profile(path)

    def test_environment_selects_rocket_02_at_import(self):
        environment = os.environ.copy()
        environment["GUIDANCE_AIRFRAME_PROFILE"] = str(
            ROOT / "deploy" / "airframes" / "rocket-02.json")
        command = [
            sys.executable, "-c",
            ("import sys; sys.path.insert(0, r'%s'); "
             "import servo_controller; print(servo_controller.NEUTRAL)" %
             str(ROOT / "src")),
        ]
        output = subprocess.check_output(
            command, env=environment, text=True).strip()
        self.assertEqual(
            output, "{7: 1525, 8: 1340, 9: 1715, 10: 1275}")

    def test_deployment_includes_selectable_airframe_profiles(self):
        defaults = (ROOT / "deploy" / "rocket-guidance.default").read_text(
            encoding="utf-8")
        installer = (ROOT / "scripts" / "install_guidance_service.sh").read_text(
            encoding="utf-8")
        self.assertIn("GUIDANCE_AIRFRAME_PROFILE=", defaults)
        self.assertIn("deploy/airframes", installer)
        self.assertIn("/etc/rocket-guidance/airframes", installer)

if __name__ == "__main__":
    unittest.main()
