from machine import Pin
from time import sleep_us, ticks_diff, ticks_us


def main():
    beams = (("L1", 21), ("L2", 20))
    pins = [Pin(gpio, Pin.IN) for _, gpio in beams]
    clear_levels = [pin.value() for pin in pins]
    levels = clear_levels[:]
    print("Using startup levels as CLEAR. Block and release L1, then L2.")
    previous = ticks_us()
    elapsed_us = 0
    for (name, gpio), level in zip(beams, levels):
        print("t_us=0 {} GP{}={} CLEAR (baseline)".format(name, gpio, level))

    while True:
        now = ticks_us()
        elapsed_us += ticks_diff(now, previous)
        previous = now
        sampled = [pin.value() for pin in pins]
        for index, level in enumerate(sampled):
            if level != levels[index]:
                levels[index] = level
                name, gpio = beams[index]
                state = "CLEAR" if level == clear_levels[index] else "BREAK"
                other = 1 - index
                other_state = "CLEAR" if sampled[other] == clear_levels[other] else "BREAK"
                print("t_us={} {} GP{}={} {} ({} {})".format(
                    elapsed_us, name, gpio, level, state, beams[other][0], other_state
                ))
        sleep_us(100)


if __name__ == "__main__":
    main()
