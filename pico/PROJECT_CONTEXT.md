# Virtual Golf Project Context

Last updated November 18, 2026.

## Architecture

A real golf ball interrupts a Starry IR break-beam sensor. A Raspberry Pi Pico 2 W running MicroPython v1.29.0 reads the receiver signal on GP21 and sends one JSON event per passage over USB serial to a Raspberry Pi 5 running Raspberry Pi OS. The Pi 5 will receive events and run the virtual game. Camera tracking is planned. There is no motorized gate or physical gate control.

```json
{"event":"ball_detected","sensor_id":1,"timestamp_ms":123456,"duration_ms":35}
```

`timestamp_ms` represents Pico uptime at the start of the interruption. `duration_ms` measures the interruption. The Pi 5 can attach a separate receipt timestamp.

## Hardware and development setup

- The Pico is connected to the Pi 5 over USB. The host serial device is `/dev/ttyACM0`. VS Code and MicroPico are installed, and the MicroPython REPL has been verified.
- The transmitter has red (+5 V) and black (GND) wires. The receiver has red (+5 V), black (GND), and white (signal) wires. The receiver documentation describes its output as both NPN and push-pull. The voltage and output type remain unverified. A 5 V-tolerant buffer powered at 3.3 V was discussed as an interface. Its installation has not been confirmed.
- The Pico input is GP21 (physical pin 27). The adjacent GND toward the USB connector is physical pin 28. A breadboard, jumpers, and a Raspberry Pi camera are available. No multimeter was available during troubleshooting.

## Milestones and current status

| Milestone | Evidence and status |
| --- | --- |
| Pico validation | `blink.py` ran on the Pico over direct USB serial. The Pico reported completion and the user saw the LED blink. MicroPico upload and run are still unverified. |
| GPIO input validation | With the Pico internal pull-up enabled, GP21 read `0` when jumpered to GND and `1` with the jumper removed. |
| Detection and rearming | `ball_sensor.py` ran on the Pico with two simulated interruptions. The Pi 5 received exactly two `ball_detected` JSON events over USB, with durations of 35 ms and 40 ms. The current active-low setting was selected for the jumper test. |
| Physical IR sensor | `sensor_live.py` streamed GPIO changes to `/tmp/golfbot-sensor-live.log` on the Pi 5. The last checked log contained only `GP21 = 1 (initial)`. The user reported the sensor was connected and said “3.3”. It is still unclear whether that refers to sensor power, signal voltage, or a buffer. Physical beam transitions and trigger polarity are pending. |
| Pi 5 event listener | USB receipt was demonstrated during the simulated detection test. A persistent listener with parsing, logging, and reconnect handling is pending. |
| Game integration | Consuming ball events in the virtual golf game and adding camera tracking are pending. |

## Next verification

Confirm the sensor power source and how the receiver's white signal wire reaches GP21. Once the input interface is verified, use `sensor_live.py` to observe the clear and blocked levels, set the trigger polarity in `ball_sensor.py`, and verify that a real ball passage produces one event on the Pi 5.
