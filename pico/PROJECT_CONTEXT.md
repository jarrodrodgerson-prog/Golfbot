# Virtual Golf Project Context

Last updated November 18, 2026.

## Architecture

A Pico 2 W running MicroPython reads two IR break-beams and sends speed measurements over USB. The Raspberry Pi 5 stores measurements and will run the virtual game. Camera tracking is future work. There is no physical gate control.

The original `ball_sensor.py` still emits one `ball_detected` line per completed interruption with Pico uptime in `timestamp_ms` and interruption duration in `duration_ms`. The dual-beam program emits one `ball_speed` line on a valid GP21-to-GP20 passage. It includes the first edge's Pico uptime (`timestamp_ms`), the time between blocked edges (`elapsed_us`), the configured distance (`beam_spacing_m`), and `speed_mph`. The Pi logger stores the parsed fields and appends a UTC receipt timestamp.

## Hardware and electrical safety

- Sensor 1 uses GP21 (physical pin 27). Sensor 2 uses GP20 (physical pin 26). The Pico's USB connection appears as `/dev/ttyACM0` on the Pi 5.
- Both transmitter/receiver pairs now use Pico VBUS 5 V with common ground, per the user. Both white wires were reported connected to the GPIOs. The Starry sensor documentation was previously described as specifying both NPN and push-pull. The actual output type and voltage are unresolved and no multimeter is available.
- Before further powered hardware testing, power off and isolate both white wires from the Pico inputs. One conditioning option is a [TI SN74LVC2G17 dual buffer](https://www.ti.com/product/SN74LVC2G17) powered from Pico 3V3 with shared ground and a 100 nF bypass capacitor at its supply pins. Check the package pinout, the exact receiver specifications, and that each receiver signal stays within the buffer's input ratings and meets its thresholds. Route each white wire to its own buffer input and each buffer output to its corresponding GPIO. For a confirmed open-collector output, a pull-up to 3V3 on the receiver side of the buffer can define the released level if the datasheet confirms compatibility. If the receiver specifications cannot establish compatibility, get the exact part documentation or have the output characterized before proceeding. The interface has not been installed or verified in this session.

## Milestones

| Check | Evidence and status |
| --- | --- |
| Pico and USB | Earlier direct USB blink test passed. User subsequently confirmed MicroPico communication and local `/dev/ttyACM0`. This workspace session has no visible Pico serial device. |
| GP21 jumper | Previously read 0 with a GND jumper and 1 after removal using a pull-up. |
| Simulated single-beam USB events | Earlier test produced two events, 35 ms and 40 ms. This test was not repeated. |
| Sensor 1 physical hand test | User observed GP21 transitions between 0 and 1 with `sensor_live.py` running on the Pico. Safe-operation verification and blocked polarity are pending. |
| Sensor 2 physical test | Newly connected per user. Independent beam transitions and polarity are pending. |
| Dual-beam firmware and Pi storage | Host-side checks passed for mixed polarity, tick wraparound, debounce, rearming, reverse order, repeated first edges, timeout, and SQLite storage from a JSON stream. Physical timing, beam spacing, and end-to-end USB storage on the Pi are pending. |
| Game integration | Pending. |

## Local test sequence

1. Establish safe conditioning for both channels before powering up. In VS Code, use MicroPico to run `dual_sensor_test.py` on the Pico. Leave both beams clear at startup. Block and clear each beam in turn while keeping the other clear. Record each channel's initial, blocked and restored values and confirm the other channel stays steady. Stop with Ctrl+C.
2. For the equivalent local terminal workflow, close MicroPico's serial connection and check who owns the port. An empty `fuser` result normally means no owner. Investigate any permission errors before opening the port.

   ```bash
   cd /home/jrod/golfbot/pico
   ls -l /dev/ttyACM0
   fuser -v /dev/ttyACM0
   python3 -m venv ~/.venvs/golfbot
   ~/.venvs/golfbot/bin/python -m pip install mpremote pyserial
   ~/.venvs/golfbot/bin/mpremote connect /dev/ttyACM0 run dual_sensor_test.py
   ```

3. Measure center-to-center beam spacing along the ball's travel in meters. Set `BEAM_SPACING_METERS`, `SENSOR_1_BLOCKED_LEVEL` and `SENSOR_2_BLOCKED_LEVEL` in `speed_sensor.py`. A valid passage starts at GP21 and reaches GP20 within the configured 2-second timeout. Firmware requires a stable transition for 300 µs and both beams clear for 10 ms before rearming. Sampling and sensor response affect timing accuracy. These timing defaults are provisional until tested with real ball speeds.
4. Stop the monitor and recheck port ownership. Start the Pico script and the Pi logger with one serial owner. Pass a ball through GP21 then GP20, repeat after both beams clear, and check for one printed and stored event per pass. Test GP20-first and GP21-only passes separately. They should produce zero measurements.

   ```bash
   fuser -v /dev/ttyACM0
   PYTHONUNBUFFERED=1 ~/.venvs/golfbot/bin/mpremote connect /dev/ttyACM0 run speed_sensor.py |
     ~/.venvs/golfbot/bin/python speed_receiver.py --stdin --database golfbot.sqlite3
   ```

   The logger can also open serial directly with `--port /dev/ttyACM0` when the Pico already runs the firmware at boot. In that mode the logger retries after a disconnect. Use Ctrl+C to end the logger.

   To inspect the latest stored rows after stopping the logger, run this from the same directory.

   ```bash
   python3 -c 'import sqlite3; db = sqlite3.connect("file:golfbot.sqlite3?mode=ro", uri=True); print(*db.execute("SELECT received_at_utc, elapsed_us, beam_spacing_m, speed_mph FROM speed_measurements ORDER BY id DESC LIMIT 10"), sep="\n")'
   ```
