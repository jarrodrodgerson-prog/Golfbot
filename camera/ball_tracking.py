"""Track a white golf ball in the Pi's live USB camera feed."""

import argparse
import csv
import signal
import sys
from collections import deque
from contextlib import ExitStack
from datetime import datetime, timezone
from dataclasses import dataclass
from math import hypot, pi
from queue import Full, Queue
from threading import Thread
from time import perf_counter

import cv2


@dataclass(frozen=True)
class BallSample:
    frame_number: int
    received_at: float
    center: tuple[int, int]
    radius: int


class BallTracker:
    """Keep a short history in full-frame pixels, with x right and y down."""

    def __init__(self):
        self.samples = deque(maxlen=20)

    def update(
        self, frame, roi, frame_number, received_at, white_min, radius_range,
        saturation_max=65, local_contrast=None,
    ):
        if self.samples and frame_number - self.samples[-1].frame_number > 3:
            self.samples.clear()

        x, y, width, height = roi
        crop = frame[y:y + height, x:x + width]

        # White pixels are bright in all three channels. Low saturation
        # helps reject colored objects with a high value channel.
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, (0, 0, white_min), (179, saturation_max, 255))
        min_circularity = min_fill = 0.65
        if local_contrast is not None:
            # Compare against an area wider than the expected ball to handle uneven lighting.
            window = 2 * min(radius_range[1], min(width, height) // 2) + 1
            brightness = cv2.extractChannel(hsv, 2)
            background = cv2.blur(brightness, (window, window))
            contrast = cv2.subtract(brightness, background)
            mask = cv2.bitwise_and(mask, cv2.inRange(contrast, local_contrast, 255))
            # Permit slightly elongated contours caused by motion blur.
            min_circularity, min_fill = 0.55, 0.50
        mask = cv2.medianBlur(mask, 3)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        best = None
        best_score = float("-inf")
        previous = self.samples[-1] if self.samples else None

        for contour in contours:
            (cx, cy), radius = cv2.minEnclosingCircle(contour)
            if not radius_range[0] <= radius <= radius_range[1]:
                continue
            if cx - radius <= 0 or cy - radius <= 0 or cx + radius >= width - 1 or cy + radius >= height - 1:
                continue

            area = cv2.contourArea(contour)
            perimeter = cv2.arcLength(contour, True)
            if perimeter == 0:
                continue
            circularity = 4 * pi * area / perimeter ** 2
            fill = area / (pi * radius ** 2)
            if circularity < min_circularity or fill < min_fill:
                continue

            center = (round(cx) + x, round(cy) + y)
            score = circularity + fill
            if previous:
                distance = hypot(center[0] - previous.center[0], center[1] - previous.center[1])
                frames_elapsed = frame_number - previous.frame_number
                score += 1 / (1 + distance / (4 * previous.radius * frames_elapsed))

            if score > best_score:
                best_score = score
                best = BallSample(frame_number, received_at, center, round(radius))

        if best is not None:
            self.samples.append(best)
        return best


def parse_args(argv=None, parser=None, defaults=None):
    if parser is None:
        parser = argparse.ArgumentParser(description=__doc__)
    display = parser.add_mutually_exclusive_group()
    display.add_argument("--headless", action="store_true", help="Skip the preview window")
    display.add_argument("--preview", dest="headless", action="store_false", help="Show the preview window")
    parser.add_argument("--video", help="Record the annotated preview to a new MJPG AVI file")
    parser.add_argument("--track-csv", help="Save detected ball centers to a new CSV file")
    parser.add_argument("--device", default="/dev/video0", help="V4L2 device")
    parser.add_argument("--roi", type=int, nargs=4, metavar=("X", "Y", "W", "H"),
                        help="Search rectangle in pixels. Defaults to the entire frame.")
    parser.add_argument("--white-min", type=int, default=190, help="Minimum HSV brightness (0–255)")
    parser.add_argument("--saturation-max", type=int, default=65,
                        help="Maximum HSV saturation (0–255)")
    parser.add_argument("--local-contrast", type=int, metavar="MIN",
                        help="Require the ball to be brighter than its surroundings (1–255)")
    parser.add_argument("--radius", type=int, nargs=2, default=(4, 80),
                        metavar=("MIN", "MAX"), help="Allowed ball radius in pixels")
    if defaults:
        parser.set_defaults(**defaults)
    args = parser.parse_args(argv)
    if args.video and not args.video.lower().endswith(".avi"):
        parser.error("--video requires an .avi filename.")
    if args.roi and (min(args.roi[:2]) < 0 or min(args.roi[2:]) < 3):
        parser.error("ROI origin must be nonnegative, with width and height at least 3.")
    if not 0 <= args.white_min <= 255:
        parser.error("--white-min must be between 0 and 255.")
    if not 0 <= args.saturation_max <= 255:
        parser.error("--saturation-max must be between 0 and 255.")
    if args.local_contrast is not None and not 1 <= args.local_contrast <= 255:
        parser.error("--local-contrast must be between 1 and 255.")
    if not 1 <= args.radius[0] <= args.radius[1]:
        parser.error("--radius requires positive values in ascending order.")
    return args


def open_camera(device):
    capture = cv2.VideoCapture(device, cv2.CAP_V4L2)
    if not capture.isOpened():
        capture.release()
        raise RuntimeError(f"Could not open {device} with V4L2.")
    try:
        capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        capture.set(cv2.CAP_PROP_FPS, 60)
    except cv2.error:
        capture.release()
        raise
    return capture


class BackgroundVideo:
    def __init__(self, writer):
        self.writer = writer
        self.frames = Queue(maxsize=4)
        self.dropped = 0
        self.error = None
        self.thread = Thread(target=self.record)
        self.thread.start()

    def record(self):
        while (frame := self.frames.get()) is not None:
            if self.error is None:
                try:
                    self.writer.write(frame)
                except cv2.error as error:
                    self.error = error

    def write(self, frame):
        try:
            self.frames.put_nowait(frame)
        except Full:
            self.dropped += 1

    def release(self):
        self.frames.put(None)
        self.thread.join()
        self.writer.release()
        if self.dropped:
            print(f"Debug video dropped {self.dropped} frames.", file=sys.stderr)
        if self.error:
            print(f"Debug video write failed: {self.error}", file=sys.stderr)


def run(
    args, track_writer=None, *, on_sample=None, stop=None,
    background_video=False, expected_size=None, on_default=None,
):
    capture = open_camera(args.device)
    video = None
    try:
        fourcc = int(capture.get(cv2.CAP_PROP_FOURCC))
        pixel_format = "".join(chr((fourcc >> (8 * i)) & 255) for i in range(4))
        print(f"V4L2 reports {pixel_format!r} "
              f"{capture.get(cv2.CAP_PROP_FRAME_WIDTH):.0f}x"
              f"{capture.get(cv2.CAP_PROP_FRAME_HEIGHT):.0f} at "
              f"{capture.get(cv2.CAP_PROP_FPS):g} FPS", file=sys.stderr, flush=True)

        tracker = BallTracker()
        frame_times = deque(maxlen=60)
        frame_number = 0
        window = "Golfbot Ball Tracking"
        while stop is None or not stop.is_set():
            ok, frame = capture.read()
            if not ok:
                raise RuntimeError(f"Could not read a frame from {args.device}.")
            received_at = perf_counter()
            received_utc = datetime.now(timezone.utc) if args.video else None
            frame_number += 1

            height, width = frame.shape[:2]
            if expected_size is not None and (width, height) != expected_size:
                raise ValueError(f"Camera frame size is {width}×{height}. Recalibrate the camera.")
            if args.video and video is None:
                with open(args.video, "xb"):
                    pass
                video = cv2.VideoWriter(
                    args.video, cv2.VideoWriter_fourcc(*"MJPG"),
                    capture.get(cv2.CAP_PROP_FPS) or 60, (width, height),
                )
                if not video.isOpened():
                    raise RuntimeError(f"Could not open recording {args.video}.")
                if background_video:
                    video = BackgroundVideo(video)

            roi = args.roi or (0, 0, width, height)
            x, y, roi_width, roi_height = roi
            if x + roi_width > width or y + roi_height > height:
                raise RuntimeError(f"ROI {tuple(roi)} exceeds the {width}x{height} frame.")

            ball = tracker.update(
                frame, roi, frame_number, received_at, args.white_min, args.radius,
                args.saturation_max, args.local_contrast,
            )
            if ball:
                if on_sample is not None:
                    on_sample(ball)
                if track_writer is not None:
                    track_writer.writerow((
                        ball.frame_number, ball.received_at, *ball.center, ball.radius,
                    ))
            if args.headless and video is None:
                continue

            if args.roi:
                cv2.rectangle(frame, (x, y), (x + roi_width - 1, y + roi_height - 1), (255, 180, 0), 1)
            centers = [sample.center for sample in tracker.samples]
            for start, end in zip(centers, centers[1:]):
                cv2.line(frame, start, end, (0, 170, 255), 2, cv2.LINE_AA)
            if ball:
                cv2.circle(frame, ball.center, ball.radius, (0, 255, 0), 2, cv2.LINE_AA)
                cv2.circle(frame, ball.center, 2, (0, 255, 0), -1)
            label = f"Ball center {ball.center}" if ball else "Ball not detected"

            frame_times.append(received_at)
            fps = (len(frame_times) - 1) / (received_at - frame_times[0]) if len(frame_times) > 1 else 0
            cv2.rectangle(frame, (0, 0), (290, 61), (0, 0, 0), -1)
            for line, baseline in ((f"Processing FPS {fps:.1f}", 23), (label, 49)):
                cv2.putText(frame, line, (10, baseline), cv2.FONT_HERSHEY_SIMPLEX,
                            0.6, (255, 255, 255), 1, cv2.LINE_AA)
            if video is not None:
                stamp = f"{frame_number}  {received_utc.isoformat(timespec='milliseconds')}"
                cv2.rectangle(frame, (0, height - 28), (460, height - 1), (0, 0, 0), -1)
                cv2.putText(frame, stamp, (10, height - 8), cv2.FONT_HERSHEY_SIMPLEX,
                            0.5, (255, 255, 255), 1, cv2.LINE_AA)
                video.write(frame)
            if not args.headless:
                cv2.imshow(window, frame)
                key = cv2.waitKey(1) & 0xFF
                if key in (ord("q"), ord("Q")):
                    break
                if on_default is not None and key in (ord("d"), ord("D")):
                    on_default()
                if cv2.getWindowProperty(window, cv2.WND_PROP_VISIBLE) < 1:
                    break
    finally:
        if video is not None:
            video.release()
        capture.release()
        if not args.headless:
            cv2.destroyAllWindows()


def run_with_outputs(args, **options):
    with ExitStack() as stack:
        track_writer = None
        if args.track_csv:
            track_file = stack.enter_context(
                open(args.track_csv, "x", newline="", buffering=1)
            )
            track_writer = csv.writer(track_file)
            track_writer.writerow(("frame", "host_monotonic_s", "x_px", "y_px", "radius_px"))
        run(args, track_writer, **options)


def main():
    args = parse_args()
    try:
        run_with_outputs(args)
    except (OSError, RuntimeError, cv2.error) as error:
        raise SystemExit(str(error)) from error
    except KeyboardInterrupt:
        pass


def stop_preview(_signum, _frame):
    raise KeyboardInterrupt


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, stop_preview)
    main()
