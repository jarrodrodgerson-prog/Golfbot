"""Combine calibrated camera aim and Pico speed on the Pi."""

import argparse
from collections import deque
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from math import atan2, degrees, isfinite, sqrt
import os
from pathlib import Path
from queue import Empty, SimpleQueue
from select import select
import signal
import sqlite3
import sys
from threading import Event, Lock, Thread
from time import perf_counter

import cv2
import numpy as np

from speed_receiver import open_database, parse_measurement, store_measurement

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "camera"))
from ball_tracking import open_camera, parse_args as parse_camera_args, run_with_outputs


CAMERA_TIMING_TOLERANCE_S = 0.20
AIM_WAIT_S = 0.15
L1_NEAR_M = 0.12
CAMERA_GRACE_S = 0.25
LATE_BEAM_TOLERANCE_S = 0.50
MPS_PER_MPH = 0.44704
DEFAULT_SPEED_MPH = 3.0


class Calibration:
    def __init__(self, image_size, corners_px, width_m, length_m):
        self.image_size = tuple(image_size)
        self.width_m = width_m
        self.length_m = length_m
        if (
            len(self.image_size) != 2
            or any(type(value) is not int or value < 3 for value in self.image_size)
            or any(not isfinite(value) or value <= 0 for value in (width_m, length_m))
        ):
            raise ValueError("Calibration needs positive dimensions and a valid frame size.")
        corners = np.array(corners_px, dtype=np.float32)
        if (
            corners.shape != (4, 2)
            or not np.isfinite(corners).all()
            or (corners < 0).any()
            or (corners >= self.image_size).any()
            or not cv2.isContourConvex(corners)
            or cv2.contourArea(corners) < 100
        ):
            raise ValueError("Select four corners in order around the measured rectangle.")
        floor = np.float32([[0, 0], [width_m, 0], [width_m, length_m], [0, length_m]])
        self.matrix = cv2.getPerspectiveTransform(corners, floor)

    def project(self, center):
        x, y, scale = self.matrix @ (*center, 1)
        if abs(scale) > 1e-9:
            return float(x / scale), float(y / scale)
        return None


@dataclass(frozen=True)
class FloorSample:
    frame: int
    time: float
    x: float
    y: float


@dataclass(frozen=True)
class BeamPass:
    event: dict
    received: float
    received_at_utc: str
    prior: float

    @property
    def transit(self):
        return self.event["elapsed_us"] / 1_000_000


@dataclass(frozen=True)
class CameraPass:
    started: float
    finished: float
    speed_mps: float | None
    aim_deg: float
    samples: int

    def matches(self, beam, tolerance=CAMERA_GRACE_S):
        return (
            abs(self.finished - beam.received) <= tolerance
            and abs(self.started - (beam.received - beam.transit)) <= tolerance
            and abs((self.finished - self.started) - beam.transit)
            <= max(0.075, 0.5 * (self.finished - self.started))
        )


def fit_velocity(points):
    times = [point.time - points[0].time for point in points]
    x = [point.x for point in points]
    y = [point.y for point in points]
    t_mean = sum(times) / len(times)
    t_variance = sum((t - t_mean) ** 2 for t in times)
    x_mean = sum(x) / len(x)
    y_mean = sum(y) / len(y)
    vx = sum((t - t_mean) * (v - x_mean) for t, v in zip(times, x)) / t_variance
    vy = sum((t - t_mean) * (v - y_mean) for t, v in zip(times, y)) / t_variance
    error = sqrt(sum(
        (px - x_mean - vx * (t - t_mean)) ** 2 + (py - y_mean - vy * (t - t_mean)) ** 2
        for t, px, py in zip(times, x, y)
    ) / len(times))
    return vx, vy, error


def fit_aim(points, beam_speed):
    span = points[-1].time - points[0].time
    if not 0 < span <= CAMERA_TIMING_TOLERANCE_S or points[-1].y - points[0].y < 0.025:
        return None
    vx, vy, error = fit_velocity(points)
    if 0.35 * beam_speed <= vy <= 2.5 * beam_speed and error <= 0.015:
        return degrees(atan2(vx, vy))
    return None


class ShotMatcher:
    def __init__(self, calibration):
        self.calibration = calibration
        self.samples = deque(maxlen=180)
        self.lock = Lock()
        self.camera_passes = SimpleQueue()
        self.last_camera_finish = float("-inf")

    def add(self, ball):
        point = self.calibration.project(ball.center)
        if point is None:
            return
        sample = FloorSample(ball.frame_number, ball.received_at, *point)
        with self.lock:
            previous = self.samples[-1] if self.samples else None
            self.samples.append(sample)
            length = self.calibration.length_m
            if previous is not None and previous.y < length <= sample.y:
                passage = self.fit_camera_pass()
                if passage is not None:
                    self.last_camera_finish = passage.finished
                    self.camera_passes.put(passage)

    def fit_camera_pass(self):
        """Fit a single forward track from near the first beam through the second."""
        length = self.calibration.length_m
        points = []
        for sample in reversed(self.samples):
            if (
                sample.time <= self.last_camera_finish
                or not 0 <= sample.x <= self.calibration.width_m
                or sample.y < -L1_NEAR_M
            ):
                break
            if points:
                later = points[-1]
                delta = later.time - sample.time
                if (
                    not 0 < delta <= 0.15
                    or later.frame - sample.frame > 3
                    or sample.y - later.y > 0.015
                    or sample.y >= length
                ):
                    break
            points.append(sample)
            if sample.y <= 0 and len(points) >= 4:
                break
        points.reverse()
        if len(points) < 3 or points[0].y > 0.15 * length:
            return None

        first = points[0]
        before, after = points[-2:]
        forward = after.y - first.y
        across = after.x - first.x
        max_error = min(0.025, 0.10 * length)
        # Check the path independently of frame timing so we can confirm a roll
        # and its heading even when the timing cannot support a speed estimate.
        if any(
            abs(point.x - first.x - across * (point.y - first.y) / forward) > max_error
            for point in points[1:-1]
        ):
            return None
        fraction = (length - before.y) / (after.y - before.y)
        finish = before.time + fraction * (after.time - before.time)
        start = first.time - first.y * (after.time - first.time) / forward
        if not 0 < finish - start <= 3:
            return None

        vx, vy, error = fit_velocity(points)
        if len(points) >= 4 and vy > 0 and error <= max_error:
            return CameraPass(start, finish, vy, degrees(atan2(vx, vy)), len(points))
        return CameraPass(start, finish, None, degrees(atan2(across, forward)), len(points))

    def match(self, event, received, previous_received):
        transit = event["elapsed_us"] / 1_000_000
        expected_l1 = received - transit
        min_time = max(previous_received, expected_l1 - CAMERA_TIMING_TOLERANCE_S)
        with self.lock:
            samples = [point for point in self.samples if point.time > min_time]

        beam_speed = event["beam_spacing_m"] / transit
        best = None
        best_score = None
        for start, anchor in enumerate(samples):
            offset = abs(anchor.time - expected_l1)
            if offset > CAMERA_TIMING_TOLERANCE_S or abs(anchor.y) > L1_NEAR_M:
                continue
            if not 0 <= anchor.x <= self.calibration.width_m:
                continue

            points = [anchor]
            for point in samples[start + 1:start + 5]:
                if (
                    point.frame - points[-1].frame > 3
                    or point.time - anchor.time > CAMERA_TIMING_TOLERANCE_S
                    or not 0 <= point.x <= self.calibration.width_m
                ):
                    break
                points.append(point)
            for count in range(len(points), 2, -1):
                angle = fit_aim(points[:count], beam_speed)
                if angle is not None:
                    # Prefer a fit that starts near L1, before ball speed can decay.
                    score = abs(anchor.y) / L1_NEAR_M + offset / CAMERA_TIMING_TOLERANCE_S
                    if best_score is None or score < best_score:
                        best, best_score = (angle, count), score
                    break
        return best


def send_game_event(output):
    print(json.dumps(output, separators=(",", ":")), flush=True)


def emit_beam(beam, aim, spacing_matches, *, aim_source="camera"):
    event = beam.event
    emitted = perf_counter()
    output = {
        "event": "golf_shot" if aim else "shot_unresolved",
        "speed_source": "beam",
        "speed_mps": event["speed_mph"] * MPS_PER_MPH,
        "speed_mph": event["speed_mph"],
        "beam_elapsed_us": event["elapsed_us"],
        "pico_timestamp_ms": event["timestamp_ms"],
        "received_at_utc": beam.received_at_utc,
        "speed_received_monotonic_s": beam.received,
        "emitted_monotonic_s": emitted,
        "processing_ms": round((emitted - beam.received) * 1000, 2),
    }
    if aim is None:
        output["reason"] = "no_reliable_camera_track" if spacing_matches else "beam_spacing_mismatch"
    else:
        output["aim_source"] = aim_source
        output["aim_deg"] = round(aim[0], 2)
        output["camera_samples"] = aim[1]
    send_game_event(output)


def emit_camera(passage, store):
    estimated_at_utc = datetime.now(timezone.utc).isoformat()
    emitted = perf_counter()
    output = {
        "event": "golf_shot",
        "aim_source": "camera",
        "aim_deg": round(passage.aim_deg, 2),
        "camera_samples": passage.samples,
        "camera_elapsed_ms": round((passage.finished - passage.started) * 1000, 2),
        "estimated_at_utc": estimated_at_utc,
        "camera_l2_monotonic_s": passage.finished,
        "emitted_monotonic_s": emitted,
        "processing_ms": round((emitted - passage.finished) * 1000, 2),
    }
    if passage.speed_mps is None:
        output.update(default_speed_fields("camera_speed_unavailable"))
    else:
        store.put((passage, estimated_at_utc))
        output.update(
            speed_source="camera",
            speed_mps=passage.speed_mps,
            speed_mph=passage.speed_mps / MPS_PER_MPH,
        )
    send_game_event(output)


def default_speed_fields(reason):
    return {
        "speed_source": "default",
        "speed_mph": DEFAULT_SPEED_MPH,
        "speed_mps": DEFAULT_SPEED_MPH * MPS_PER_MPH,
        "fallback_reason": reason,
    }


def emit_manual(requested, beam):
    if beam is not None:
        emit_beam(beam, (0.0, 0), True, aim_source="default")
        return
    emitted = perf_counter()
    send_game_event({
        "event": "golf_shot",
        **default_speed_fields("manual"),
        "aim_source": "default",
        "aim_deg": 0.0,
        "camera_samples": 0,
        "estimated_at_utc": datetime.now(timezone.utc).isoformat(),
        "emitted_monotonic_s": emitted,
        "processing_ms": round((emitted - requested) * 1000, 2),
    })


def find_camera_pass(beam, passages):
    return min(
        (passage for passage in passages if passage.matches(beam, LATE_BEAM_TOLERANCE_S)),
        key=lambda passage: (
            abs(passage.finished - beam.received)
            + abs(passage.started - (beam.received - beam.transit))
        ),
        default=None,
    )


def emit_shots(matcher, store, stop, manual_requests=None):
    """Read beam events and give them priority over a complete camera pass."""
    partial = b""
    discard = False
    pending_beams = deque()
    pending_camera = deque()
    recent_beams = deque(maxlen=16)
    recent_camera = deque(maxlen=16)
    emitted_camera = deque(maxlen=16)
    previous_received = float("-inf")
    source_open = True
    manual_requested = None
    last_manual = last_game_shot = float("-inf")
    if manual_requests is None:
        manual_requests = SimpleQueue()

    while True:
        while True:
            try:
                passage = matcher.camera_passes.get_nowait()
            except Empty:
                break
            pending_camera.append(passage)
            recent_camera.append(passage)

        while True:
            try:
                requested = manual_requests.get_nowait()
            except Empty:
                break
            if manual_requested is None and requested - last_game_shot > LATE_BEAM_TOLERANCE_S:
                manual_requested = requested

        has_pending = pending_beams or pending_camera or manual_requested is not None
        if (stop.is_set() or not source_open) and not has_pending:
            break
        timeout = 0.01 if has_pending else 0.10
        if select([sys.stdin] if source_open else [], [], [], timeout)[0]:
            chunk = os.read(sys.stdin.fileno(), 4096)
            receipt = perf_counter()
            received_at_utc = datetime.now(timezone.utc).isoformat()
            source_open = bool(chunk)
            lines = (partial + chunk).split(b"\n")
            partial = lines.pop()
            for line in lines:
                event = None if discard or len(line) > 4096 else parse_measurement(line)
                discard = False
                if event is not None:
                    beam = BeamPass(event, receipt, received_at_utc, previous_received)
                    store.put((beam, received_at_utc))
                    recent_beams.append(beam)
                    pending_beams.append(beam)
                    previous_received = receipt
            if len(partial) > 4096:
                partial = b""
                discard = True

        while pending_beams:
            beam = pending_beams[0]
            passage = find_camera_pass(beam, recent_camera)
            if (
                (passage is not None and passage in emitted_camera)
                or abs(beam.received - last_manual) <= LATE_BEAM_TOLERANCE_S
            ):
                # Preserve the hardware reading in SQLite and emit only one game shot.
                pending_beams.popleft()
                continue
            spacing_matches = abs(beam.event["beam_spacing_m"] - matcher.calibration.length_m) <= 0.005
            aim = None
            if spacing_matches:
                aim = matcher.match(beam.event, beam.received, beam.prior)
                if aim is None and passage is not None and passage.matches(beam):
                    aim = passage.aim_deg, passage.samples
                if aim is None and perf_counter() - beam.received < AIM_WAIT_S:
                    break
            pending_beams.popleft()
            emit_beam(beam, aim, spacing_matches)
            if aim is not None:
                last_game_shot = perf_counter()

        while pending_camera:
            passage = pending_camera[0]
            if (
                abs(passage.finished - last_manual) <= LATE_BEAM_TOLERANCE_S
                or any(find_camera_pass(beam, recent_camera) is passage for beam in recent_beams)
            ):
                pending_camera.popleft()
                continue
            if perf_counter() < passage.finished + CAMERA_GRACE_S:
                break
            pending_camera.popleft()
            emit_camera(passage, store)
            emitted_camera.append(passage)
            last_game_shot = perf_counter()

        if manual_requested is not None:
            if last_game_shot >= manual_requested - LATE_BEAM_TOLERANCE_S:
                manual_requested = None
            elif (
                not (pending_beams or pending_camera)
                and perf_counter() >= manual_requested + CAMERA_GRACE_S
            ):
                beam = next(
                    (b for b in reversed(recent_beams)
                     if abs(b.received - manual_requested) <= LATE_BEAM_TOLERANCE_S),
                    None,
                )
                emit_manual(manual_requested, beam)
                last_manual = manual_requested
                last_game_shot = perf_counter()
                manual_requested = None
    stop.set()


def open_shot_database(path):
    db = open_database(path)
    try:
        with db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS camera_speed_estimates (
                    id INTEGER PRIMARY KEY,
                    estimated_at_utc TEXT NOT NULL,
                    speed_mps REAL NOT NULL,
                    aim_deg REAL NOT NULL,
                    camera_elapsed_ms REAL NOT NULL,
                    camera_samples INTEGER NOT NULL
                )"""
            )
    except sqlite3.Error:
        db.close()
        raise
    return db


def save_speeds(path, store):
    with closing(open_shot_database(path)) as db:
        while (measurement := store.get()) is not None:
            passage, stamp = measurement
            if isinstance(passage, BeamPass):
                store_measurement(db, passage.event, stamp)
            else:
                with db:
                    db.execute(
                        """INSERT INTO camera_speed_estimates
                           (estimated_at_utc, speed_mps, aim_deg, camera_elapsed_ms, camera_samples)
                           VALUES (?, ?, ?, ?, ?)""",
                        (stamp, passage.speed_mps, passage.aim_deg,
                         (passage.finished - passage.started) * 1000, passage.samples),
                    )


def run_live(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calibration", required=True, type=Path, help="Measured floor calibration JSON")
    parser.add_argument("--database", required=True, type=Path)
    args = parse_camera_args(argv, parser, defaults={
        "headless": True, "roi": (0, 105, 1280, 420), "radius": (20, 65),
        "white_min": 120, "saturation_max": 110, "local_contrast": 16,
    })
    matcher = ShotMatcher(Calibration(**json.loads(args.calibration.read_text())))
    stop = Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    store = SimpleQueue()
    manual_requests = SimpleQueue()
    failures = SimpleQueue()

    def request_default(*_):
        manual_requests.put(perf_counter())

    signal.signal(signal.SIGUSR1, request_default)

    def worker(operation, *args):
        try:
            operation(*args)
        except (OSError, sqlite3.Error, ValueError) as error:
            failures.put(error)
            stop.set()

    # Verify the schema and path before accepting hardware events.
    with closing(open_shot_database(args.database)):
        pass
    storage = Thread(target=worker, args=(save_speeds, args.database, store))
    speed = Thread(target=worker, args=(emit_shots, matcher, store, stop, manual_requests))
    storage.start()
    speed.start()
    try:
        run_with_outputs(
            args, on_sample=matcher.add, stop=stop, background_video=True,
            expected_size=matcher.calibration.image_size, on_default=request_default,
        )
    finally:
        stop.set()
        speed.join()
        store.put(None)
        storage.join()
    if not failures.empty():
        raise failures.get()


def calibrate(argv):
    parser = argparse.ArgumentParser(description="Calibrate from a measured rectangle spanning L1 to L2.")
    parser.add_argument("--device", default="/dev/video0")
    parser.add_argument("--width-in", type=float, required=True, help="Measured width across each beam")
    parser.add_argument("--length-in", type=float, default=11, help="Measured distance between beams")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    if any(not isfinite(value) or value <= 0 for value in (args.width_in, args.length_in)):
        parser.error("Rectangle dimensions must be positive.")
    if args.output.exists():
        parser.error("Choose a new calibration filename.")
    capture = open_camera(args.device)
    try:
        ok, frame = capture.read()
        if not ok:
            raise RuntimeError("Could not capture a calibration frame.")
    finally:
        capture.release()

    points = []
    labels = ("L1 left", "L1 right", "L2 right", "L2 left")

    def click(event, x, y, _flags, _param):
        if event == cv2.EVENT_LBUTTONDOWN and len(points) < len(labels):
            points.append([x, y])

    window = "Golfbot floor calibration"
    cv2.namedWindow(window, cv2.WINDOW_AUTOSIZE)
    cv2.setMouseCallback(window, click)
    try:
        while True:
            preview = frame.copy()
            prompt = f"Click {labels[len(points)]}" if len(points) < 4 else "Enter saves"
            cv2.putText(preview, f"{prompt}   R resets   Q quits", (12, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2, cv2.LINE_AA)
            for label, point in zip(labels, points):
                x, y = point
                cv2.circle(preview, (x, y), 5, (0, 255, 255), -1)
                cv2.putText(preview, label, (x + 8, y - 4), cv2.FONT_HERSHEY_SIMPLEX,
                            0.55, (0, 255, 255), 1, cv2.LINE_AA)
            cv2.imshow(window, preview)
            key = cv2.waitKey(30) & 0xFF
            if key in (ord("q"), ord("Q")) or cv2.getWindowProperty(window, cv2.WND_PROP_VISIBLE) < 1:
                return
            if key in (ord("r"), ord("R")):
                points.clear()
            if key in (10, 13) and len(points) == 4:
                data = {
                    "image_size": [frame.shape[1], frame.shape[0]], "corners_px": points,
                    "width_m": args.width_in * 0.0254, "length_m": args.length_in * 0.0254,
                }
                try:
                    Calibration(**data)
                except ValueError as error:
                    print(error, file=sys.stderr)
                    points.clear()
                    continue
                with args.output.open("x") as file:
                    json.dump(data, file, indent=2)
                    file.write("\n")
                print(f"Saved {args.output}")
                return
    finally:
        cv2.destroyAllWindows()


def main():
    try:
        if sys.argv[1:2] == ["calibrate"]:
            calibrate(sys.argv[2:])
        else:
            run_live(sys.argv[1:])
    except KeyboardInterrupt:
        pass
    except (OSError, RuntimeError, ValueError, TypeError, sqlite3.Error, cv2.error) as error:
        raise SystemExit(f"Golfbot: {error}") from error


if __name__ == "__main__":
    main()
