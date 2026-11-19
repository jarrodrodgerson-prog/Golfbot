#!/usr/bin/python3
"""Serve the existing TeeOff France course with live Pi shot input."""

import argparse
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from math import isfinite
import os
from pathlib import Path
import signal
import subprocess
import sys
from threading import Condition, Thread
from urllib.parse import urlsplit


HERE = Path(__file__).resolve().parent


class ShotFeed:
    def __init__(self, replay, diagnostics=None):
        self.changed = Condition()
        self.events = deque(maxlen=32)
        self.sequence = 0
        self.replay = replay
        self.diagnostics = diagnostics
        self.process = None
        self.status = {"ready": replay is not None, "text": (
            "Ready to replay a saved shot." if replay is not None else "Starting Pico and camera…"
        )}

    def publish(self, kind, data):
        with self.changed:
            if kind == "status":
                self.status = data
            self.sequence += 1
            self.events.append((self.sequence, kind, data))
            self.changed.notify_all()

    def set_status(self, ready, text):
        self.publish("status", {"ready": ready, "text": text})

    def start(self, calibration):
        command = [str(HERE / "run_camera_beam_test.sh"), "--game", str(calibration)]
        if self.diagnostics is not None:
            command.extend((
                "--video", str(self.diagnostics / "preview.avi"),
                "--track-csv", str(self.diagnostics / "track.csv"),
            ))
        self.process = subprocess.Popen(
            command,
            cwd=HERE, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, start_new_session=True,
        )
        Thread(target=self.read_shots, daemon=True).start()
        Thread(target=self.read_status, daemon=True).start()

    def read_shots(self):
        with self.process.stdout as stream:
            for line in stream:
                try:
                    shot = json.loads(line)
                except ValueError:
                    continue
                if isinstance(shot, dict):
                    self.publish("shot", shot)
                    line = json.dumps(shot)
                    if self.diagnostics is not None:
                        with (self.diagnostics / "shots.jsonl").open("a") as log:
                            log.write(line + "\n")
                    print(line, flush=True)
        self.set_status(False, "Live shot input stopped. See the Pi terminal.")

    def read_status(self):
        with self.process.stderr as stream:
            for line in stream:
                print(line, end="", file=sys.stderr, flush=True)
                if line.startswith("V4L2 reports"):
                    self.set_status(True, "Ready. Roll through L1 → L2.")

    def request_shot(self):
        if self.replay is not None:
            with self.changed:
                shot = next(self.replay, None)
                if shot is None:
                    self.set_status(False, "Replay complete.")
                    return False
                self.publish("shot", shot)
                return True
        if not self.status["ready"] or self.process.poll() is not None:
            return False
        try:
            self.process.send_signal(signal.SIGUSR1)
        except ProcessLookupError:
            return False
        return True

    def close(self):
        if self.process is None or self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            os.killpg(self.process.pid, signal.SIGKILL)
            self.process.wait()


class CourseRequest(BaseHTTPRequestHandler):
    def same_host(self):
        if self.headers.get("Host") == self.server.authority:
            return True
        self.send_error(403)
        return False

    def do_GET(self):
        if not self.same_host():
            return
        path = urlsplit(self.path).path
        if path == "/":
            self.reply(self.server.page, "text/html; charset=utf-8")
        elif path == "/golfbot-france.js":
            self.reply(self.server.script, "text/javascript; charset=utf-8")
        elif path == "/events":
            self.stream_events()
        else:
            self.send_error(404)

    def do_POST(self):
        if not self.same_host():
            return
        if self.path != "/shot":
            self.send_error(404)
            return
        if self.headers.get("Origin") != f"http://{self.server.authority}":
            self.send_error(403)
            return
        self.send_response(204 if self.server.feed.request_shot() else 409)
        self.end_headers()

    def reply(self, body, content_type):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def stream_events(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        feed = self.server.feed
        with feed.changed:
            cursor, status = feed.sequence, feed.status
        try:
            self.send_event("status", status)
            while True:
                with feed.changed:
                    feed.changed.wait_for(lambda: feed.sequence > cursor, timeout=10)
                    events = [event for event in feed.events if event[0] > cursor]
                for cursor, kind, data in events:
                    self.send_event(kind, data)
                if not events:
                    self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def send_event(self, kind, data):
        self.wfile.write(f"event: {kind}\ndata: {json.dumps(data)}\n\n".encode())
        self.wfile.flush()


def load_replay(path):
    for line in path.read_text().splitlines():
        try:
            shot = json.loads(line)
        except ValueError:
            continue
        if isinstance(shot, dict) and shot.get("event") == "golf_shot":
            yield shot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--course-dir", type=Path, default=HERE / "course" / "france")
    parser.add_argument("--calibration", type=Path, default=HERE / "floor-calibration.json")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--pixels-per-meter", type=float, default=600,
                        help="Board pixels per calibrated meter for the virtual shot speed")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--replay", type=Path, help="Use saved shots and leave the camera and Pico free")
    source.add_argument("--diagnostics", type=Path, help="Save a live video, camera track, and shot log")
    args = parser.parse_args()
    if not isfinite(args.pixels_per_meter) or args.pixels_per_meter <= 0:
        parser.error("--pixels-per-meter must be finite and positive.")
    course = args.course_dir / "index.html"
    if not course.is_file():
        parser.error(f"Could not find the course at {course}.")
    if args.replay is not None and not args.replay.is_file():
        parser.error(f"Could not find the shot log at {args.replay}.")
    page = course.read_bytes()
    if b"</body>" not in page:
        parser.error("The course HTML is missing its closing body tag.")
    bridge = (
        f'<script defer src="/golfbot-france.js" data-speed-scale="{args.pixels_per_meter}"'
        f' data-replay="{int(args.replay is not None)}"></script>\n'
    ).encode()
    diagnostics = args.diagnostics.resolve() if args.diagnostics is not None else None
    feed = ShotFeed(load_replay(args.replay) if args.replay is not None else None, diagnostics)
    with ThreadingHTTPServer(("127.0.0.1", args.port), CourseRequest) as server:
        server.authority = f"127.0.0.1:{server.server_port}"
        server.page = page.replace(b"</body>", bridge + b"</body>", 1)
        server.script = (HERE / "golfbot_france.js").read_bytes()
        server.feed = feed

        def stop(_signal, _frame):
            raise KeyboardInterrupt

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGHUP, stop)
        try:
            if diagnostics is not None:
                diagnostics.mkdir()
                (diagnostics / "shots.jsonl").touch(exist_ok=False)
            if args.replay is None:
                feed.start(args.calibration.resolve())
            print(f"France course: http://{server.authority}/?mouse=0", flush=True)
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            feed.close()


if __name__ == "__main__":
    main()
