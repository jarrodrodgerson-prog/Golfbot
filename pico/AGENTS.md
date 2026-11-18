# Virtual Golf Pico Workspace

- Read `PROJECT_CONTEXT.md` before making changes. Update it as milestones are completed, recording how each milestone was verified and what is still pending.
- Keep the Pico 2 W responsible for reading the beam and sending events over USB serial. Keep game logic on the Raspberry Pi 5. Camera tracking is future work. The project has no motorized gate or physical gate control.
- Use MicroPython on the Pico. The sensor input is GP21 (physical pin 27). Resolve the receiver output voltage and input interface before connecting an unverified signal to GP21.
- Preserve one `ball_detected` JSON line per completed interruption. Use Pico uptime for `timestamp_ms` and milliseconds for `duration_ms`. The Pi 5 can add its own receipt timestamp.
- Check who owns the USB serial port before opening it. MicroPico and a direct serial monitor cannot independently read the same stream.
- Record simulated inputs, jumper checks, and physical sensor tests separately so the project status reflects what was exercised.
