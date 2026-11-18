from machine import Pin
from time import sleep_ms, ticks_diff, ticks_ms


def main():
    pin = Pin(21, Pin.IN)
    level = pin.value()
    last_change = ticks_ms()
    print("Watching GP21. Block and clear the beam. Ctrl+C stops the feed.")
    print("GP21 = {} (initial)".format(level))

    while True:
        current = pin.value()
        if current != level:
            now = ticks_ms()
            print("GP21 = {} (previous level held {} ms)".format(
                current, ticks_diff(now, last_change)
            ))
            level = current
            last_change = now
        sleep_ms(1)


if __name__ == "__main__":
    main()
