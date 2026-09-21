"""Pure always-on landing-pad guidance state machine."""

from dataclasses import dataclass
from enum import Enum
from math import hypot

from camera_zones import decide_with_hysteresis
from servo_controller import NEUTRAL, bounded_pulses_for


class State(Enum):
    STARTING = "starting"
    SEARCHING = "searching"
    ACQUIRING = "acquiring"
    LOCKED = "locked"
    LOST = "lost"
    FAULT = "fault"
    INHIBITED = "inhibited"


@dataclass(frozen=True)
class Observation:
    center: tuple[int, int]
    frame_size: tuple[int, int]
    area_fraction: float
    captured_at: float


@dataclass(frozen=True)
class GuidanceOutput:
    state: State
    pulses: dict[int, int]
    requested_us: int = 0
    target: tuple[int, int] | None = None
    reason: str = ""
    acquire_count: int = 0


class GuidanceController:
    def __init__(self, settings, max_offset=400, acquire_frames=3,
                 loss_timeout=0.5):
        self.settings = settings
        self.max_offset = max_offset
        self.acquire_frames = acquire_frames
        self.loss_timeout = loss_timeout
        self.state = State.SEARCHING
        self.acquire_count = 0
        self.previous_observation = None
        self.lost_since = None
        self.latched = False
        self.last_output = self._output(State.SEARCHING)

    def _output(self, state, pulses=None, requested=0, target=None,
                reason="", acquire_count=None):
        return GuidanceOutput(
            state=state,
            pulses=dict(NEUTRAL if pulses is None else pulses),
            requested_us=requested,
            target=target,
            reason=reason,
            acquire_count=(self.acquire_count if acquire_count is None
                           else acquire_count),
        )

    @staticmethod
    def _compatible(previous, current):
        if previous is None or current is None:
            return False
        if previous.frame_size != current.frame_size:
            return False
        short_side = min(current.frame_size)
        movement = hypot(current.center[0] - previous.center[0],
                         current.center[1] - previous.center[1])
        if movement > 0.12 * short_side:
            return False
        if previous.area_fraction <= 0 or current.area_fraction <= 0:
            return False
        ratio = current.area_fraction / previous.area_fraction
        return 0.5 <= ratio <= 2.0

    def _save(self, output):
        self.state = output.state
        self.last_output = output
        return output

    def _searching(self, reason=""):
        self.acquire_count = 0
        self.previous_observation = None
        self.lost_since = None
        return self._save(self._output(State.SEARCHING, reason=reason,
                                       acquire_count=0))

    def _locked_output(self, observation):
        previous_requested = (self.last_output.requested_us
                              if self.state in (State.LOCKED, State.LOST)
                              else 0)
        decision = decide_with_hysteresis(
            observation.center, observation.frame_size, previous_requested,
            max_tested_us=self.max_offset)
        pulses = bounded_pulses_for(decision, self.settings)
        self.previous_observation = observation
        self.lost_since = None
        return self._save(self._output(
            State.LOCKED, pulses, decision.requested_us,
            observation.center, acquire_count=self.acquire_frames))

    def _missing_locked_target(self, now):
        if self.state == State.LOCKED:
            self.lost_since = now
        if self.lost_since is not None and now - self.lost_since >= self.loss_timeout:
            return self._searching("target lost")
        held = self.last_output
        return self._save(self._output(
            State.LOST, held.pulses, held.requested_us, None,
            "target temporarily lost", self.acquire_frames))

    def update(self, observation, now):
        if self.latched:
            return self.last_output
        if self.state in (State.LOCKED, State.LOST):
            if observation is None or not self._compatible(
                    self.previous_observation, observation):
                return self._missing_locked_target(now)
            return self._locked_output(observation)
        if observation is None:
            return self._searching()
        if self._compatible(self.previous_observation, observation):
            self.acquire_count += 1
        else:
            self.acquire_count = 1
        self.previous_observation = observation
        if self.acquire_count >= self.acquire_frames:
            return self._locked_output(observation)
        return self._save(self._output(
            State.ACQUIRING, target=observation.center,
            acquire_count=self.acquire_count))

    def inhibit(self):
        self.latched = True
        self.acquire_count = 0
        return self._save(self._output(State.INHIBITED, reason="operator stop",
                                       acquire_count=0))

    def fault(self, reason):
        self.latched = True
        self.acquire_count = 0
        return self._save(self._output(State.FAULT, reason=reason,
                                       acquire_count=0))
