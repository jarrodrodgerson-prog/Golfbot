from machine import Pin
from time import sleep_us, ticks_diff, ticks_us


def main():
    gpios = (21, 20)
    pins = [Pin(gpio, Pin.IN) for gpio in gpios]
    levels = [pin.value() for pin in pins]
    previous = ticks_us()
    elapsed_us = 0
    for gpio, level in zip(gpios, levels):
        print("t_us=0 GP{}={} (initial)".format(gpio, level))

    while True:
        now = ticks_us()
        elapsed_us += ticks_diff(now, previous)
        previous = now
        sampled = [pin.value() for pin in pins]
        for index, level in enumerate(sampled):
            if level != levels[index]:
                levels[index] = level
                print("t_us={} GP{}={}".format(elapsed_us, gpios[index], level))
        sleep_us(100)


if __name__ == "__main__":
    main()
