import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bench_ball_sim import NEUTRAL, expected_settings


class FakeLink:
    settings = expected_settings()

    def __init__(self):
        self.sent = []
        self.closed = False

    def send(self, pulses):
        self.sent.append(dict(pulses))

    def close(self):
        self.closed = True


class CameraBenchTests(unittest.TestCase):
    def test_stream_part_has_jpeg_headers_and_payload(self):
        from live_camera_bench import mjpeg_part

        self.assertEqual(mjpeg_part(b"\xff\xd8sample\xff\xd9"),
                         b"--frame\r\nContent-Type: image/jpeg\r\n"
                         b"Content-Length: 10\r\n\r\n"
                         b"\xff\xd8sample\xff\xd9\r\n")

    def test_page_uses_continuous_image_stream(self):
        from live_camera_bench import PAGE

        self.assertIn(b'src="/stream.mjpg"', PAGE)

    def test_pad_left_commands_recorded_top_bottom_pair(self):
        from live_camera_bench import command_for_target

        self.assertEqual(command_for_target((200, 240), (640, 480),
                                            expected_settings(), 200),
                         {7: 1505, 8: 1660, 9: 1170, 10: 1200})

    def test_missing_pad_commands_neutral(self):
        from live_camera_bench import command_for_target

        self.assertEqual(command_for_target(None, (640, 480),
                                            expected_settings(), 200), NEUTRAL)

    def test_session_returns_neutral_and_closes_link(self):
        from live_camera_bench import run_camera_session

        link = FakeLink()
        run_camera_session(link, lambda: ((200, 240), (640, 480), time.monotonic()),
                           threading.Event(), duration=0.08, max_offset=200)
        self.assertIn({7: 1505, 8: 1660, 9: 1170, 10: 1200}, link.sent)
        self.assertEqual(link.sent[-1], NEUTRAL)
        self.assertTrue(link.closed)

    def test_stale_camera_frame_commands_neutral(self):
        from live_camera_bench import command_for_sample

        self.assertEqual(command_for_sample(((200, 240), (640, 480), -10),
                                            now=1, settings=expected_settings(),
                                            max_offset=200), NEUTRAL)


if __name__ == "__main__":
    unittest.main()
