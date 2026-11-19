# Virtual Golf Project Context

Last updated November 18, 2026.

## Architecture

A Pico 2 W running MicroPython reads two IR break-beams and sends speed measurements over USB. The Raspberry Pi 5 stores measurements and will run the virtual game. The Pi also runs the OpenCV webcam tracker for a white golf ball against a dark background. There is no physical gate control.

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

1. Establish safe conditioning for both channels before powering up. Leave both beams clear before using MicroPico to run `dual_sensor_test.py` on the Pico. The script uses each startup level as its clear baseline. Block and release L1 (GP21), then L2 (GP20). Each should report `BREAK` and then `CLEAR` with the other channel marked `CLEAR` on both lines. Record the raw blocked level shown for each channel. Stop with Ctrl+C.
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

## Camera tracking

The Dell WB3023 USB webcam has been tested on the Raspberry Pi 5 at `/dev/video0` with MJPG, 1280×720, and 60 FPS. The user reported approximately 59.7 FPS in the streaming test.

The tracker requests that V4L2 mode and displays a live feed, full-frame ball center, recent trail, and measured processing FPS. The ROI, brightness threshold, and ball radius range can be adjusted from the command line. See the [camera setup and run instructions](../camera/README.md).

Synthetic checks passed for a moving white circle, ROI offsets, rejection of test distractors, and history expiry. An earlier run processed 120 webcam frames with GUI calls bypassed.

On November 18, 2026, the Dell webcam at `/dev/video0` reported MJPG at 1280×720 and 60 FPS. The tracker ran with the desktop preview enabled, displayed 180 frames at 36.8 FPS with the default full-frame search, and exited normally. Detection with a real moving golf ball, camera calibration, and high-speed tracking validation are pending.

The live real-ball test was started on the Pi desktop on November 18, 2026. The tracker opened the Dell webcam at `/dev/video0` and reported MJPG at 1280×720 and 60 FPS. Observation of a physical ball roll and its tracking trail is pending.

## Combined camera and beam test

The user confirmed that both receiver outputs have safe interfaces. The interface details and the raw clear and blocked levels for each beam remain to be recorded.

From a terminal on the Pi desktop, close MicroPico's serial connection and leave both beams clear. Install mpremote using the local test sequence above if needed, then run:

```bash
cd /home/jrod/golfbot/pico
./run_camera_beam_test.sh
```

The camera preview shows the ball center and trail. The terminal shows the Pico's raw GPIO levels and beam transitions. After both startup baselines print, block and release L1 and L2 independently, then roll a ball through the camera view and both beams. Watch for the trail and a BREAK/CLEAR pair from each beam. Press Q in the preview or Ctrl+C in the terminal to stop both. Camera tracker options can be passed to the launcher, and PICO_PORT can override /dev/ttyACM0.

Software verification on November 18, 2026 passed Bash syntax, option forwarding, missing-mpremote handling, and startup and cleanup command sequencing with a simulated serial runner. Joint hardware startup and shutdown, independent hand checks, and a real ball roll remain pending.

The MicroPico REPL screenshot showed L1 at GP21 reporting CLEAR at 1 and BREAK at 0. L2 was marked BREAK on the visible complete L1 lines, so this does not establish independent beam operation or L2 polarity. The screenshot also showed the old test ending with KeyboardInterrupt. Installed and verified mpremote 1.29.0 in the Pi's launcher virtual environment. VS Code still owned /dev/ttyACM0 when checked, so the combined test was not started.

Corrected the launcher's serial ownership check for the Pi's fuser, which rejected the previous argument separator. A brief combined hardware startup opened the Dell webcam at MJPG 1280×720 and 60 FPS and read both Pico GPIOs high at startup (GP21=1, GP20=1). The script labels startup levels CLEAR automatically, and beam positions were not observed during this check. After stopping the launcher, fuser reported no owner for either device. Independent beam transitions and a real ball roll are pending.

In the combined test preview, the user showed a stationary golf ball in frame with “Ball not detected” at 56.6 processing FPS. The visible ball radius (about 39 px) is within the default 4–80 px filter. The photo shows a strong hotspot next to the ball and a shaded side. Retest stationary detection with diffuse lighting and a dark matte surface before judging moving-ball tracking. The same screenshot shows an L1 BREAK at 0 and CLEAR at 1 with L2 marked CLEAR on both lines. L2 independent transitions are still pending.

A second preview screenshot showed a blue-tinted ball and no detection. Added a configurable HSV saturation limit to the camera tracker and set the combined launcher to 110 (standalone tracker defaults to 65). A synthetic 39 px blue-tinted ball was rejected at 65 and detected at 110 with the correct center and radius. Real stationary and moving-ball verification of the new setting is pending.

The user measured 11 inches (0.2794 m) between L1 and L2, treated as center-to-center along the direction of travel. L1 was observed independently at 1 clear and 0 blocked. L2 read 1 at startup, but its blocked level still requires an independent test. The running combined test prints transitions to its terminal and did not save a camera track or speed measurement.

Configured the measured distance and L1 polarity in speed_sensor.py. The firmware still requires an independently verified L2 blocked level before speed mode can run. Added optional camera recording via `./run_camera_beam_test.sh --track-csv ball-track.csv` with a new filename for each run. Each detection records frame, monotonic host time, pixel center, and pixel radius. A simulated camera integration check verified the CSV and cleanup, and a 100 ms crossing time at 11 inches was verified to convert to 6.25 mph. Camera target-line and plane calibration and the first real stored speed remain pending.

A recorded real roll in ball-track.csv contained 51 ball-sized detections in frames 559–613, from (158, 396) to (1230, 336) over about 1.02 s. A line fit gives about 3.1 degrees above image horizontal, with travel to the right. Small 4–6 px detections elsewhere were excluded. Target-line calibration and a stored beam speed remain pending.

After the L2 repair, the combined test logged an independent L2 transition at GP20=0 blocked and GP20=1 clear with L1 clear. L1 also independently reported GP21=0 blocked and GP21=1 clear. A subsequent L1-to-L2 sequence had break edges at 20,762,757 and 21,256,552 µs, yielding 0.493795 s and an estimated 1.27 mph from the diagnostic timestamps. The camera CSV from the same run captured a six-detection segment moving up-left, with a fitted image-plane angle of about 30.6° above leftward horizontal. The diagnostic timestamps and camera CSV use different clocks, so the segment has not been matched to the beam passage. Confirming a real ball produces one stored speed event remains pending.

The Pico speed firmware and Pi SQLite logger ran with both beams configured active-low and 0.2794 m spacing. After the user reported a faster ball roll, the live logger had printed no speed event and the database still contained zero rows. The cause is unresolved. A beam-only roll in the same direction and at a similar speed can show whether each beam transitions and in what order.

A second speed-mode roll also left the database empty. A subsequent real roll in the raw beam diagnostic produced L2 BREAK at 35,472,433 µs and L1 BREAK at 35,756,284 µs, with clean CLEAR transitions for both beams. That observed order is GP20 then GP21, which speed mode rejects by design. Restarted the unchanged L1-to-L2 speed test and Pi logger. A forward roll that produces one stored measurement remains pending.

The next real L1-to-L2 roll produced exactly one stored ball_speed measurement in golfbot.sqlite3 (row 1). The Pico measured 147,938 µs over 0.2794 m, and the Pi stored 4.224743 mph with receipt timestamp 2026-11-19T01:25:41.982286+00:00 (November 18 at 7:25:41 p.m. Central). This verifies a forward real-ball pass through the Pico USB speed pipeline and Pi storage.

The combined launcher now supports --speed with the existing Pico speed firmware and Pi SQLite logger, and the camera supports --video for an annotated AVI. The recording spans the test so it includes the lead-up and captures misses even when no valid beam event is emitted. Each video frame has a frame number and host UTC receipt time for approximate comparison to the speed logger's UTC receipt time. The track CSV retains its existing format. A real-device start/stop smoke test produced a readable 64-frame AVI and released both devices. Started combined-20261118-193006.avi and its matching CSV for a new physical roll. A matched camera track and stored speed from the same real roll remain pending.

Reviewed the finalized combined video around frames 2445–2457. The ball was visible moving right to left, roughly horizontally in the image. The detector outlined it only once (frame 2449, center 566/375, radius 30 px) and labeled several unrelated 4–7 px spots before and after the roll. Nearby frames show the ball blurred and crossing bands of uneven illumination. One reliable automatic center is insufficient for an angle fit. SQLite still contained only the previous 4.224743 mph row, so this combined run did not yield a speed measurement.

Added an optional local-contrast detector for the Pi camera. It compares each pixel's brightness with the nearby floor and permits some elongation from motion blur. For the recorded setup, use `--roi 0 275 1280 250 --radius 20 65 --white-min 120 --local-contrast 16` with the combined launcher, which already supplies saturation max 110. Full replay of all 4,480 annotated video frames recovered 13 ball centers from frames 2443–2457 with no detections elsewhere at these settings. The original live CSV had one reliable center for that roll. A straight-line fit to the recovered centers gave 5.5° up from leftward image horizontal. Live confirmation on the new setup and a calibrated angle relative to the target line are pending. The user's black lines at the laser positions can serve as visual references for beam crossings.

The live next-roll test saved exactly one new speed row (row 2), 1.7895286 mph over 349,254 µs at 0.2794 m, received at 2026-11-19T01:45:19.581748+00:00. The live camera CSV recorded four ball centers (frames 446–449, from 196/361 to 330/320). The video shows the ball continuing above the search rectangle, crossing the second visible laser mark. Replaying all 711 frames using `--roi 0 105 1280 420` and the same detector settings recovered 14 ball centers, with no other detections in that replay. The image-plane fitted path moved right and up at about 15.4° above horizontal. The angle relative to the physical target line and exact camera-to-beam synchronization remain unverified.

## Game input on the Pi

The game launcher emits live JSON lines on stdout. The Pi runs the camera and matches a short forward path near L1 to the Pico's speed event. Normal game mode runs with the preview off. Use `--preview` when setting up the lane. The Pico firmware and 11-inch beam spacing are shared with the existing speed test.

For calibration, mark two points on each beam's black line to make a measured rectangle. Its long axis should follow the intended direction of travel and the midpoint between the two side edges should be the target line. Measure the width across each beam. From the Pi desktop terminal, run the calibration tool with that width in inches. Here 8 is an example width and should be replaced with the actual measurement.

```bash
/usr/bin/python3 shot_input.py calibrate --width-in 8 --output floor-calibration.json
```

Click L1 left, L1 right, L2 right, and L2 left as viewed facing the direction of travel. Press Enter to save. Recalibrate after changing the camera position, camera framing, or beam positions. The calibrator uses an 11-inch length by default.

```bash
./run_camera_beam_test.sh --game floor-calibration.json --preview
```

For the game, start the same command without `--preview` and read each JSON line from stdout. Start the simulated ball on `golf_shot` using `speed_mps` and `aim_deg`. Zero degrees is forward and positive angles are to the right when facing L2. `shot_unresolved` indicates a speed was captured but no matching reliable aim was available or the calibration spacing differs from the firmware. When needed, the launcher waits about 150 ms for late camera frames. Report launch latency by measuring from `speed_received_monotonic_s` to the first animated frame on the same Pi monotonic clock. `processing_ms` measures only from completed Pico line receipt to the Pi producing the shot event.

Speed rows still go to `golfbot.sqlite3` through a background writer. For a short diagnostic recording, add `--video debug.avi` with a new filename. The background video writer can drop frames when encoding falls behind. Frame numbers and UTC receipt times are stamped on the video.

A simulated tracked ball and fragmented Pico event produced a single game shot at 1.00 m/s and +18.43 degrees. A second event with no matching path emitted `shot_unresolved`, and both speed rows were stored. A seven-second real-device startup and shutdown check used disposable calibration with no roll. It saved a readable 224-frame AVI with 32 debug frames dropped, kept status messages off game stdout, and released the camera and USB port. Physical calibration, a live matched game shot, and first-render latency in a game client are pending.

The shiny red-grid camera-only test (red-grid-20261118-201529) recorded 529 video frames. The live tracker found 10 ball centers over 0.359 s from frame 359 to 369, with one gap at frame 366 and no detections elsewhere in the CSV. Video review showed the missed ball blurred beside the bright reflection on the grid's left edge. The roll traversed the red surface right to left and the fitted path rose 2.0 degrees relative to image horizontal. No beam speed or calibrated aim was measured in this camera-only run.

In the combined red-grid test (red-grid-combined-20261118-201727), video showed the ball traveling rapidly right to left in frames 231–235, visibly elongated by motion blur. The live detector saved only frame 232 at (813, 455), so an automatic angle fit was unavailable. SQLite stayed at two speed rows. An earlier accepted forward roll on this camera setup traveled left to right, so confirm the physical L1-to-L2 direction on the next combined roll.

The second combined red-grid recording (red-grid-combined-20261118-201915) captured seven ball centers from frames 155–163, with image positions moving from (1147, 343) to (60, 337) over 0.321 s. The fitted image direction was 0.29 degrees up from leftward horizontal. No new speed row was stored. The camera again observed right-to-left travel; the corresponding physical beam order was not recorded in speed mode.

In the follow-up beam-only real roll, L1 broke at 14,109,868 µs and cleared at 14,119,976 µs (10.108 ms). L2 stayed clear throughout the observed events. This pass reached L1, with no raw L2 transition for the speed firmware to time. The next check is an independent L2 hand interruption at the ball path with L1 clear.

The independent beam check produced an L2 BREAK at GP20=0 and CLEAR at GP20=1 with L1 clear on both lines. L1 also responded in a separate interruption. The L2 interruption lasted about 490 ms. L2 responds to an obstruction, while the prior real roll showed only L1. Whether the ball blocks L2 along its actual rolling path remains to be checked.

A further ball pass produced L1 BREAK/CLEAR only, lasting 11.489 ms. L2 had previously responded independently, so the repeatable issue is the ball failing to interrupt L2 on its rolling path. Check L2 with the golf ball stationary at the expected crossing and verify the beam intersects the ball at floor level before repeating a full roll.

When the user reported passing L2, the raw test instead logged GP21 (L1) blocked for 1.095 s, with GP20 (L2) clear. The physical beam or mark used for that check may have been misidentified. Identify the two physical beams by covering each receiver independently and matching it to the GPIO shown before checking the ball at the L2 mark again.

A subsequent real ball roll in the raw diagnostic triggered both beams in reverse order. GP20 (L2) broke at 257,682,382 µs and GP21 (L1) broke at 258,056,134 µs. The separation was 373,752 µs, giving about 1.67 mph over 0.2794 m as a diagnostic estimate. This verifies the ball can interrupt both sensors on its current path. The speed program still accepts L1 then L2.

The next raw roll produced only an L2 break at 305,106,167 µs and clear at 305,116,763 µs (10.596 ms). L1 stayed clear, so no transit speed could be derived. A simultaneous camera and raw beam run can help identify the ball's physical route relative to the two receiver locations.

The synchronized red-grid raw diagnostic (red-grid-beam-check-20261118-202638) saved seven ball centers over 0.325 s and video of the ball crossing the full red area from right to left. The fitted image direction was 2.63 degrees above leftward horizontal. The timestamped Pico log showed L1 breaking during that tracked path for 16.539 ms; there was no L2 transition. No speed is available. Check the physical L2 beam at the exact ball path before repeating a combined speed roll.

### Camera speed fallback

Game mode now prefers a Pico speed event and can estimate speed when one or both beam breaks are missing. Enable it with the normal calibrated game command, `./run_camera_beam_test.sh --game floor-calibration.json --preview`. The diagnostic `--speed` mode continues to show the individual hardware measurements.

A camera speed estimate requires at least four consistent ball detections across the calibrated lane, starting near L1 and continuing past L2 in the forward direction. It estimates forward speed and signed aim from a fit to calibrated positions and host frame times. The game waits about 250 ms from the camera's L2 crossing to give the Pico priority. Game events identify `speed_source` as `beam` or `camera`. Camera estimates are saved separately in `camera_speed_estimates` and reflected in `camera_elapsed_ms` and `camera_l2_monotonic_s` on the game event. A matching late beam event within the association window is stored as a hardware reading without launching a second game shot. Estimates assume motion near the calibrated floor plane and can be less accurate on a bounce.

Software checks used synthetic ball images with a calibrated test rectangle and a fragmented serial feed. The no-event case emitted a correctly scaled camera-only shot and stored one estimate. The timely Pico case emitted a beam shot, and the late Pico case saved the hardware reading while emitting one camera shot. Reverse, partial, and late-start tracks produced no shot. Physical floor calibration and a live fallback roll remain pending.

### Default shot speed

When the camera confirms a forward crossing and can determine aim but cannot produce a reliable speed estimate, game mode emits 3.0 mph (1.34112 m/s) with `speed_source: "default"` and retains the camera aim. A matching Pico reading still takes priority while the shot is pending. A late matching Pico event is saved separately and does not trigger a second game shot.

If neither input confirms a roll, game mode stays idle. After a missed roll, press **D** with the game preview focused, or send SIGUSR1 to the running game launcher from a headless client after startup. This requests one shot, uses a recent measured beam speed if available for the missed shot, and otherwise uses 3 mph. A manual shot uses straight-ahead aim (`aim_source: "default"`). Default speeds are not stored in the measurement or estimate tables.

Simulated tests covered the 3 mph fallback with camera aim, manual 3 mph with zero aim, camera and beam priority, late beam deduplication, and suppression for idle, partial, and reverse tracks. A mocked camera preview verified the D key. A real Pi launcher smoke test with disposable calibration emitted exactly one 3 mph manual shot via SIGUSR1, stayed running, then released the camera and Pico on shutdown. A calibrated live test of the automatic default remains pending.

Saved floor-calibration.json for the red-grid setup using the user-measured 11-inch width and 11-inch beam spacing. The calibration loaded successfully for 1280×720 and all four saved image corners projected to the expected 0.2794 m square. A straight physical roll in game mode remains pending to verify the selected marks, forward direction, and angle near zero.

The first calibrated game-mode roll (calibrated-game-20261118-204312) recorded 15 live camera detections. With the saved corner order the path went from beyond L2 to beyond L1, decreasing from 18.67 to -6.16 inches in the calibrated forward coordinate. No game shot, Pico speed, or camera fallback row was emitted. An offline replay with the two beam sides reversed in memory fit 10 samples across the lane at about 4.08 mph and -3.22 degrees relative to the reverse direction. The saved calibration was not changed. A roll from the left side of the camera preview toward the right is needed to verify the currently calibrated forward direction.

A real forward roll in calibrated game mode (calibrated-game-20261118-204546) produced exactly one golf_shot. The Pico measured 138,782 µs over 11 inches and SQLite saved row 3 at 4.503466 mph (2.013229 m/s). Three camera centers gave a calibrated aim of -0.13 degrees, slightly left of straight ahead, from 15 live detections overall. The Pi emitted the game event 30.86 ms after receiving the Pico measurement. This verifies the live calibrated beam-plus-camera path. A live automatic speed fallback and first-render latency in the game client remain pending.

## Local 2D course integration

The Pi reached the requested Azure DevOps TeeOff - France Git endpoint, but the server required credentials and Git has no configured credential helper. The desktop folder named TeeOff - France has no refs, objects, or source files. The adjacent local Turkey Tee Off desktop app has a playable 2D green. The Pi adapter in `play_putting.py` reuses that app's existing course renderer and putting physics.

Run `/usr/bin/python3 play_putting.py` to open the 2D course with calibrated Pico and camera input. It defaults to the local Turkey Tee Off folder and the saved calibration. The adapter turns each game shot's speed and signed aim into lateral and forward velocities. After a roll ends, click **Next shot**. Use **D** to request the fallback after a missed roll. Close the course window to release the devices. Add `--preview` to also show the camera. Use `--replay calibrated-game-20261118-204546.shots.jsonl` to play the saved test on the course without opening the Pico or camera.

On the Pi desktop, the saved 4.50 mph, -0.13 degree real measurement moved the rendered ball forward and left. A separate live launcher test moved the rendered ball using one 3 mph manual fallback and released the devices on shutdown. The game displays latency through its first drawn frame. A real live roll into the 2D course and access to the France repository remain pending.

The first physical putt into the 2D course worked using the live camera fallback. SQLite saved one camera estimate at 1.571106 m/s (3.51 mph), aim -0.95 degrees, with 12 samples and about 176 ms through the calibrated lane. The user then clicked Next shot and reported two rolls with no response. The webcam and Pico were still active, and neither missed roll left a speed row or camera estimate. The run had no frame recording, so the physical cause cannot be reconstructed.

Added optional `play_putting.py --diagnostics NEW_DIRECTORY` to save the preview video, camera track and timestamped Next shot controls with game events. A live Pi test triggered two manual fallback shots with Next shot between them. Both moved the ball in the same running course, and the diagnostic log and AVI were readable. Restarted the course with capture in course-diagnostic-20261118-205650 for the next physical roll. The cause of the two missed rolls remains pending.

## TeeOff France integration

The user successfully cloned the Azure DevOps France course to `/home/jrod/teeoff-france`. `play_france.py` serves the existing course on Pi loopback at `http://127.0.0.1:8765/?mouse=0` and loads `golfbot_france.js` to pass calibrated game events to the course's existing MiniGolf API. The France checkout remained clean. The bridge maps one meter per second to 600 board pixels per second by default (adjustable with `--pixels-per-meter`), and maps straight physical aim to the current cup bearing. Signed aim offsets keep their physical left/right meaning.

Run `/usr/bin/python3 play_france.py` from the Pico workspace for live game input. The browser provides **Fallback shot** and the original **Reset** control. For an offline demonstration, add `--replay calibrated-game-20261118-204546.shots.jsonl`. Stop the launcher with Ctrl+C to release the camera and Pico.

Chromium replay launched the saved real 4.50 mph, 0.13-degree-left putt once at 1207.94 board pixels/second. A separate live Pico/camera test delivered one 3 mph default shot through the France event stream and released the devices. The France browser page and its event stream are open on the Pi for a physical putt. The preceding Turkey Tee Off diagnostic also confirmed a real 3.42 mph camera shot, followed by Next shot and a real 3.10 mph beam shot. A live physical roll into France remains pending.

Bundled the self-contained France course at `course/france/index.html` from TeeOff France commit `30f84a4`. The file includes the board art, collision mask, and game logic. It matched the source byte for byte and the HTML had no external asset URLs. The Pi launcher now serves that workspace copy by default, with the existing local shot bridge and saved calibration. Verified the default course and bridge responses in replay mode with the live devices untouched. The external clone remains available for source updates.

The first live France shot used beam speed 1.675473 mph and camera aim -9.30 degrees, stored as beam row 5 and sent to Chromium. The user reported a second roll after Reset, but the live bridge and database had no second shot or estimate. Added a clear ready status after browser Reset and an optional `play_france.py --diagnostics NEW_DIRECTORY` mode that records video, camera tracks, and game shot events. Verified in Chromium that two saved physical shots both launched with Reset between them and that the status returned to ready. Restarted the France service with capture in france-diagnostic-20261118-211317. The physical cause of the second roll's missing event remains unconfirmed.

The France bridge now displays a heading arrow at the stationary ball. Left and Right rotate the aim in five-degree steps, Up faces the cup, and Down turns 180 degrees. The virtual shot combines the selected heading with the signed physical camera aim. Reset returns to cup-facing aim. Chromium replay verified all four keys, the arrow's motion and visibility, the combined launch direction, and Reset. The live bridge was restarted with the new script and normal recording settings.

The France heading arrow is now visible only while an aim key is held. Releasing the key hides the arrow and retains the aim. It also hides when the tab loses focus, a shot starts, or the course is reset. Chromium verified the idle, held, release, blur, and reset behavior and confirmed the selected heading still launches the shot after key release. Restarted the live service and reopened the camera after the preceding run reported a frame-read error.

The France heading arrow now stays visible for 500 ms after the final aim key is released, then fades over 200 ms. Resuming aim cancels the fade and restores full opacity. Chromium verified the delay, timer reset, and retained shot direction. Restarted the live service with the update.

In the France session after the arrow fade update, the first two physical shots produced 3.16 mph from the beams and 3.52 mph from the camera. The user reported a third miss. There was no third game event or stored measurement, and both sensor processes remained active. Diagnostics were off for this session, so the physical cause of this individual miss cannot be determined.

On November 19, 2026, added a Next hole button and a hole number to the bundled France course. The second hole uses an alternate tee at (500, 620) on the existing green and shares the original cup and par. Next hole resets the ball, strokes, and aim, and wraps back to hole 1 after hole 2. Reset replays the selected hole. Headless Chromium verified advance during a shot, the second tee's cup bearing and successful putt, Reset on hole 2, and wraparound. Live physical play on hole 2 is pending.

Installed TeeOff France and Golf Camera Calibration launchers on the Pi desktop on November 19, 2026. The game icon opens the live course in the browser. The calibration icon uses the current 11-by-11-inch rectangle and replaces floor-calibration.json only after four points are accepted and saved. Launching both desktop entries through GIO confirmed live game readiness and camera calibration startup. The calibration smoke test exited without saving and the active file hash stayed the same. A new physical calibration was not performed.

Replaced the alternate tee with a dedicated second hole, Le virage de Paris. Its fairway turns 45 degrees at the bend, with a diagonal opening putt and a horizontal approach to a separate cup. The live bridge's default aim and Up key target the bend until the ball can reach the cup directly. Headless Chromium verified the original hole, the blocked direct route on hole 2, the exact 45-degree opening angle, a successful two-putt sequence, Reset, and hole selection wraparound. A physical putt through the new layout remains pending.

On November 19, 2026, archived course-diagnostic-20261118-205650 and france-diagnostic-20261118-211317 under /media/jrod/AC84-8B4B/Golfbot Diagnostics. Both USB copies passed recursive byte-for-byte comparison before the local originals were removed. The Pi regained 5.1 GiB of free internal storage.

Added Previous hole beside Next hole on November 19, 2026. Both controls wrap around the course and reset the selected hole's ball, stroke count, and aim. Headless Chromium verified both directions, backward navigation during a shot, Reset on hole 2, and button visibility at a 480 px window width. Physical play after navigation remains pending.

Live tracking uses the webcam, floor-calibration.json, and the detector settings in shot_input.py. AVI files are optional diagnostic outputs. They can be archived or deleted after review without affecting calibration or live tracking. The eight workspace AVI files occupied about 599 MiB. Keep a known-good roll and a representative missed roll for future detector comparisons if space allows. Keep the calibration JSON and the smaller CSV and JSONL files for track review and game replay. No recordings were removed.

On November 19, 2026, enabled the Pi user timer golfbot-video-cleanup.timer. It checks hourly and deletes local diagnostic AVI files more than 24 hours after their last write. It covers top-level AVI files and preview.avi in course-diagnostic-* and france-diagnostic-* folders. Open videos and videos with a matching .avi.keep file are skipped. For example, create next-roll.avi.keep next to next-roll.avi to retain that video. The USB archives are outside the cleanup scope.

The cleanup test deleted expired temporary videos while retaining recent, open, pinned, and symlinked files, calibration, and CSVs. The installed service exited successfully, and systemd listed its next run. All eight existing workspace videos were still within retention at setup, and the calibration checksum matched the previous check. The first scheduled deletion of an actual recording remains pending.

Launched TeeOff France live on November 19, 2026 after stopping an orphaned game-input launcher that held the Pico and webcam. The new game input acquired both devices, and the browser event stream reported ready for an L1-to-L2 roll. A physical putt in this session remains pending.

Updated the TeeOff France desktop launcher on November 19, 2026 to open a new Chromium window once the course responds, with xdg-open as a fallback on systems without Chromium. Started the updated launcher in the Pi desktop session. Confirmed Chromium connected to the live server and showed hole 1 with the ready status in the foreground. A physical putt remains pending.
