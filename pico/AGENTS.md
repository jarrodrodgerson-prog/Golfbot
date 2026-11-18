# Virtual Golf Pico Workspace

- Read `PROJECT_CONTEXT.md` before making changes. Update it with verification evidence and pending work as milestones are completed.
- Keep beam acquisition and speed measurement on the Pico 2 W and game logic and storage on the Raspberry Pi 5. Camera tracking is future work. The project has no physical gate control.
- Run scripts that import `machine.Pin` on the Pico with MicroPython using MicroPico or the local USB commands in `PROJECT_CONTEXT.md`. Run `speed_receiver.py` with Python 3 on the Pi 5.
- GP21 (physical pin 27) is sensor 1 and GP20 (physical pin 26) is sensor 2. Treat both as 3.3 V inputs. Power down and isolate both white receiver wires from the GPIOs until each 5 V-powered output has a documented safe interface. Use common ground. The 3.3 V supply or pull-up alone does not establish that an unknown output is safe.
- Check USB serial port ownership before opening it. Close MicroPico's serial connection before using a direct monitor or runner.
- Test each conditioned beam independently with the other beam clear. Record clear and blocked levels for each in the project context before configuring speed firmware. Measure the beam spacing along the direction of travel.
- Preserve the existing single-beam `ball_detected` JSON format with Pico uptime for `timestamp_ms` and milliseconds for `duration_ms`. Dual-beam firmware sends `ball_speed` events and the Pi records a separate UTC receipt timestamp.
- Record software checks, jumper checks, hand tests, and real ball tests separately. Verify ordering, timeout and rearming, then confirm a real ball passage produces one stored measurement.
