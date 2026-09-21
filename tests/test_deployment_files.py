import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DeploymentFileTests(unittest.TestCase):
    def read(self, relative):
        path = ROOT / relative
        self.assertTrue(path.exists(), f"Missing {relative}")
        return path.read_text(encoding="utf-8")

    def test_service_runs_locally_without_network_dependency(self):
        unit = self.read("deploy/rocket-guidance.service")
        self.assertIn("User=pi", unit)
        self.assertIn("WorkingDirectory=/home/pi/rocket", unit)
        self.assertIn("EnvironmentFile=-/etc/default/rocket-guidance", unit)
        self.assertIn("Restart=on-failure", unit)
        self.assertIn("RestartSec=2", unit)
        self.assertIn("TimeoutStopSec=8", unit)
        self.assertIn("KillSignal=SIGINT", unit)
        self.assertNotIn("network-online.target", unit)

    def test_service_uses_native_runtime_arguments(self):
        unit = self.read("deploy/rocket-guidance.service")
        self.assertIn("/home/pi/rocket/venv/bin/python", unit)
        self.assertIn("/home/pi/rocket/autonomous_guidance.py", unit)
        self.assertIn("--serial /dev/serial0", unit)
        self.assertIn("--port 8766", unit)
        self.assertIn("--max-offset ${GUIDANCE_MAX_OFFSET}", unit)
        self.assertIn("$GUIDANCE_MODE_ARG", unit)
        self.assertNotIn("${GUIDANCE_MODE_ARG}", unit)

    def test_initial_defaults_are_400_us_observe_only(self):
        defaults = self.read("deploy/rocket-guidance.default")
        self.assertIn("GUIDANCE_MAX_OFFSET=400", defaults)
        self.assertIn("GUIDANCE_MODE_ARG=--observe-only", defaults)

    def test_defaults_enable_fifteen_fps_rolling_recording(self):
        defaults = self.read("deploy/rocket-guidance.default")
        self.assertIn("GUIDANCE_TARGET_FPS=15", defaults)
        self.assertIn("GUIDANCE_EXPOSURE_VALUE=-1.0", defaults)
        self.assertIn("GUIDANCE_RECORDING=1", defaults)
        self.assertIn("GUIDANCE_RECORDING_DIR=/home/pi/rocket/recordings",
                      defaults)
        self.assertIn("GUIDANCE_RECORDING_FPS=15", defaults)
        self.assertIn("GUIDANCE_RECORDING_BITRATE=2000000", defaults)
        self.assertIn("GUIDANCE_RECORDING_SEGMENT_SECONDS=60", defaults)
        self.assertIn("GUIDANCE_RECORDING_KEEP_SEGMENTS=60", defaults)

    def test_service_passes_recording_arguments(self):
        unit = self.read("deploy/rocket-guidance.service")
        self.assertIn("--target-fps ${GUIDANCE_TARGET_FPS}", unit)
        self.assertIn("--exposure-value ${GUIDANCE_EXPOSURE_VALUE}", unit)
        self.assertIn("--recording ${GUIDANCE_RECORDING}", unit)
        self.assertIn("--recording-dir ${GUIDANCE_RECORDING_DIR}", unit)
        self.assertIn("--recording-fps ${GUIDANCE_RECORDING_FPS}", unit)
        self.assertIn("--recording-bitrate ${GUIDANCE_RECORDING_BITRATE}", unit)
        self.assertIn(
            "--recording-segment-seconds ${GUIDANCE_RECORDING_SEGMENT_SECONDS}",
            unit)
        self.assertIn(
            "--recording-keep-segments ${GUIDANCE_RECORDING_KEEP_SEGMENTS}",
            unit)

    def test_installer_enables_but_does_not_start_service(self):
        script = self.read("scripts/install_guidance_service.sh")
        self.assertIn("systemctl daemon-reload", script)
        self.assertIn("systemctl enable rocket-guidance.service", script)
        self.assertNotIn("systemctl start", script)
        self.assertNotIn("systemctl restart", script)
        self.assertIn("/home/pi/rocket/logs", script)
        self.assertIn("/home/pi/rocket/recordings", script)

    def test_native_runtime_uses_async_servo_dispatcher(self):
        runtime = self.read("src/autonomous_guidance.py")
        self.assertIn("AsyncServoDispatcher", runtime)
        self.assertIn("AsyncServoDispatcher(servo).start()", runtime)

    def test_installer_refreshes_defaults_to_safe_observe_only_config(self):
        script = self.read("scripts/install_guidance_service.sh")
        self.assertNotIn("if [ ! -e /etc/default/rocket-guidance ]", script)
        self.assertIn(
            '"$PROJECT_DIR/deploy/rocket-guidance.default"', script)
        self.assertIn("/etc/default/rocket-guidance", script)

    def test_logrotate_is_bounded(self):
        config = self.read("deploy/rocket-guidance.logrotate")
        self.assertIn("/home/pi/rocket/logs/guidance.log", config)
        self.assertIn("rotate 4", config)
        self.assertIn("size 2M", config)


if __name__ == "__main__":
    unittest.main()
