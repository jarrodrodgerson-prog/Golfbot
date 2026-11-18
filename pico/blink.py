from machine import Pin
from time import sleep_ms


def main():
    led = Pin("LED", Pin.OUT, value=0)
    print("Pico LED test started")
    try:
        for _ in range(5):
            led.on()
            sleep_ms(500)
            led.off()
            sleep_ms(500)
    finally:
        led.off()
    print("Pico LED test complete")


if __name__ == "__main__":
    main()
