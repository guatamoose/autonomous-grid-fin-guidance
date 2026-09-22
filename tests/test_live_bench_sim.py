import importlib.util
import sys
import threading
import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))
from bench_ball_sim import VirtualScene, expected_settings


def load_live_sim():
    path = SRC / "live_bench_sim.py"
    spec = importlib.util.spec_from_file_location("live_bench_sim", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class LiveBenchSimulationTests(unittest.TestCase):
    def test_displayed_ball_and_real_pulses_use_same_target(self):
        live = load_live_sim()
        frame = live.make_frame(VirtualScene(), expected_settings(), 400)
        self.assertEqual(frame["ball"], {"x": 470, "y": 130})
        self.assertEqual(frame["requested_us"], 400)
        self.assertEqual(frame["pulses"],
                         {"7": 1742, "8": 1107, "9": 1923, "10": 1163})

    def test_live_run_sends_displayed_pulses_then_returns_to_neutral(self):
        live = load_live_sim()
        stop = threading.Event()
        frames = []

        class Link:
            settings = expected_settings()

            def __init__(self):
                self.commands = []
                self.closed = False

            def send(self, pulses):
                self.commands.append(dict(pulses))

            def close(self):
                self.closed = True

        link = Link()

        def show(frame):
            frames.append(frame)
            stop.set()

        live.run_session(link, show, stop, duration=20, max_offset=400)
        self.assertEqual(len(frames), 1)
        self.assertEqual(link.commands[1],
                         {int(k): v for k, v in frames[0]["pulses"].items()})
        self.assertEqual(link.commands[-1],
                         {7: 1505, 8: 1430, 9: 1600, 10: 1400})
        self.assertTrue(link.closed)


if __name__ == "__main__":
    unittest.main()
