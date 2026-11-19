import json
from machine import Pin
from time import sleep_us, ticks_diff, ticks_ms, ticks_us


BEAM_SPACING_METERS = 0.2794  # 11 inches along the ball’s path.
SENSOR_1_BLOCKED_LEVEL = 0  # GP21 observed clear at 1 and blocked at 0.
SENSOR_2_BLOCKED_LEVEL = 0  # GP20 observed clear at 1 and blocked at 0.
DEBOUNCE_US = 300
REARM_US = 10_000
TIMEOUT_US = 2_000_000
POLL_US = 100


class Beam:
    def __init__(self, gpio, blocked_level):
        self.pin = Pin(gpio, Pin.IN)
        self.blocked_level = blocked_level
        self.raw = self.blocked = self.pin.value() == blocked_level
        self.changed_at = ticks_us()

    def sample(self, now):
        raw = self.pin.value() == self.blocked_level
        if raw != self.raw:
            self.raw = raw
            self.changed_at = now
        if raw != self.blocked and ticks_diff(now, self.changed_at) >= DEBOUNCE_US:
            self.blocked = raw
            if raw:
                return self.changed_at
        return None


def main():
    if not isinstance(BEAM_SPACING_METERS, (int, float)) or not (
        0 < BEAM_SPACING_METERS < float("inf")
    ):
        raise ValueError("Set BEAM_SPACING_METERS to the measured beam spacing")
    if SENSOR_1_BLOCKED_LEVEL not in (0, 1) or SENSOR_2_BLOCKED_LEVEL not in (0, 1):
        raise ValueError("Set each blocked level using dual_sensor_test.py")

    beam1 = Beam(21, SENSOR_1_BLOCKED_LEVEL)
    beam2 = Beam(20, SENSOR_2_BLOCKED_LEVEL)
    clear_since = None
    armed = False
    first_edge = None
    first_ms = None
    uptime_us = ticks_ms() * 1000
    previous = ticks_us()

    while True:
        now = ticks_us()
        uptime_us += ticks_diff(now, previous)
        previous = now
        edge1 = beam1.sample(now)
        edge2 = beam2.sample(now)

        if first_edge is not None:
            if edge2 is not None:
                elapsed_us = ticks_diff(edge2, first_edge)
                if edge1 is None and 0 < elapsed_us <= TIMEOUT_US:
                    print(json.dumps({
                        "event": "ball_speed",
                        "timestamp_ms": first_ms,
                        "elapsed_us": elapsed_us,
                        "beam_spacing_m": BEAM_SPACING_METERS,
                        "speed_mph": BEAM_SPACING_METERS * 1_000_000 / elapsed_us / 0.44704,
                    }))
                first_edge = None
            elif edge1 is not None or ticks_diff(now, first_edge) > TIMEOUT_US + DEBOUNCE_US + POLL_US:
                first_edge = None
        elif armed:
            if edge1 is not None or edge2 is not None:
                armed = False
                clear_since = None
                if edge1 is not None and edge2 is None and not beam2.blocked:
                    first_edge = edge1
                    first_ms = (uptime_us - ticks_diff(now, edge1)) // 1000
        elif beam1.raw or beam2.raw or beam1.blocked or beam2.blocked:
            clear_since = None
        elif clear_since is None:
            clear_since = now
        elif ticks_diff(now, clear_since) >= REARM_US:
            armed = True

        sleep_us(POLL_US)


if __name__ == "__main__":
    main()
