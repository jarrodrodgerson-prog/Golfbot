import json
from machine import Pin
from time import sleep_ms, ticks_diff, ticks_ms


SENSOR_ID = 1
GPIO = 21
BLOCKED_LEVEL = 0  # Ground jumper simulates a blocked beam.
REARM_MS = 10


def monitor(pin, run_ms=None):
    now = ticks_ms()
    started = now
    uptime_ms = 0
    blocked_at = None
    clear_at = None
    armed = False

    while run_ms is None or uptime_ms < run_ms:
        previous = now
        now = ticks_ms()
        uptime_ms += ticks_diff(now, previous)
        if pin.value() == BLOCKED_LEVEL:
            clear_at = None
            if armed:
                blocked_at = uptime_ms
                armed = False
        else:
            if clear_at is None:
                clear_at = uptime_ms
            if not armed and uptime_ms - clear_at >= REARM_MS:
                if blocked_at is not None:
                    print(json.dumps({
                        "event": "ball_detected",
                        "sensor_id": SENSOR_ID,
                        "timestamp_ms": blocked_at + started,
                        "duration_ms": clear_at - blocked_at,
                    }))
                    blocked_at = None
                armed = True
        sleep_ms(1)


if __name__ == "__main__":
    monitor(Pin(GPIO, Pin.IN, Pin.PULL_UP))
