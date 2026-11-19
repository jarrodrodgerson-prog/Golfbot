#!/usr/bin/python3
"""Play Pico and camera shots on the local Turkey Tee Off 2D course."""

import argparse
import json
from math import cos, radians, sin
import os
from pathlib import Path
import signal
import subprocess
import sys
from threading import Event
from time import monotonic
import tkinter as tk
from tkinter import ttk


HERE = Path(__file__).resolve().parent
LOCAL_COURSE = Path.home() / "Desktop" / "turkey tee off"


def launch_values(event):
    if not isinstance(event, dict) or event.get("event") != "golf_shot":
        return None
    speed, aim = event.get("speed_mps"), event.get("aim_deg")
    if (
        type(speed) not in (int, float)
        or type(aim) not in (int, float)
        or not 0 < speed < float("inf")
        or not -90 < aim < 90
    ):
        return None
    heading = radians(aim)
    return {"vx": speed * sin(heading), "vy": speed * cos(heading)}


class CourseWindow:
    def __init__(self, root, game, draw_course, *, replay=None, shot_log=None):
        self.root = root
        self.game = game
        self.draw_course = draw_course
        self.replay = replay
        self.shot_log = shot_log
        self.process = None
        self.live_ready = False
        self.streams = {}
        self.stop = Event()
        self.last_tick = monotonic()
        self.waiting_for_frame = None

        root.title("Turkey Tee Off • 2D putting")
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.bind("<KeyPress-d>", self.request_default)
        root.bind("<KeyPress-D>", self.request_default)
        self.game_canvas = tk.Canvas(root, width=800, height=570, bg="#123d24", highlightthickness=0)
        self.game_canvas.pack()
        self.shot_status = tk.StringVar(value="Waiting for a shot")
        self.input_status = tk.StringVar(value="Starting calibrated input…" if replay is None else "Replaying saved shot events")
        self.latency_status = tk.StringVar()
        ttk.Label(root, textvariable=self.shot_status, font=("Sans", 14)).pack(pady=(8, 4))
        ttk.Label(root, textvariable=self.input_status, wraplength=780).pack()
        ttk.Label(root, textvariable=self.latency_status).pack()
        buttons = ttk.Frame(root)
        buttons.pack(pady=8)
        ttk.Button(buttons, text="Next shot", command=self.next_shot).pack(side="left", padx=4)
        self.manual_button = ttk.Button(
            buttons, text="Use fallback shot", command=self.request_default, state="disabled",
        )
        self.manual_button.pack(side="left", padx=4)
        self.animate()

    def animate(self):
        self.draw_course(self)
        if self.waiting_for_frame is not None:
            submitted, received = self.waiting_for_frame
            self.waiting_for_frame = None
            self.root.after_idle(self.report_frame, submitted, received)

    def report_frame(self, submitted, received):
        visible = monotonic()
        ui_time = (visible - submitted) * 1000
        if received is None:
            self.latency_status.set(f"Game input to first rendered frame: {ui_time:.0f} ms")
        else:
            total = (visible - received) * 1000
            self.latency_status.set(f"Speed receipt to first rendered frame: {total:.0f} ms")

    def log_event(self, event):
        if self.shot_log is not None:
            self.shot_log.write(json.dumps(event, separators=(",", ":")) + "\n")

    def receive_shot(self, line):
        try:
            event = json.loads(line)
        except (ValueError, UnicodeError):
            return False
        if not isinstance(event, dict):
            return False
        self.log_event(event)
        if event.get("event") == "shot_unresolved":
            self.input_status.set("No reliable aim. Press D to request a straight-ahead shot.")
            return False

        values = launch_values(event)
        if values is None or self.game.state != "ready":
            return False
        submitted = monotonic()
        self.game.launch(values)
        beam_receipt = event.get("speed_received_monotonic_s")
        use_receipt = (
            self.replay is None and type(beam_receipt) in (int, float)
            and submitted - 5 < beam_receipt <= submitted
        )
        self.waiting_for_frame = submitted, beam_receipt if use_receipt else None
        speed = event["speed_mps"] / 0.44704
        aim = event["aim_deg"]
        source = {"beam": "Pico", "camera": "camera estimate", "default": "fallback"}.get(
            event.get("speed_source"), "shot input",
        )
        self.shot_status.set(f"{speed:.2f} mph  •  {aim:+.2f}°  •  {source}")
        self.input_status.set("Use Next shot when the ball stops.")
        return True

    def start_live(self, calibration, preview, diagnostics=None):
        command = [str(HERE / "run_camera_beam_test.sh"), "--game", str(calibration)]
        if preview:
            command.append("--preview")
        if diagnostics is not None:
            command.extend((
                "--video", str(diagnostics / "preview.avi"),
                "--track-csv", str(diagnostics / "track.csv"),
            ))
        self.process = subprocess.Popen(
            command, cwd=HERE, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, start_new_session=True,
        )
        for pipe, callback in (
            (self.process.stdout, self.receive_shot), (self.process.stderr, self.receive_status),
        ):
            os.set_blocking(pipe.fileno(), False)
            self.streams[pipe] = b"", callback
            self.root.createfilehandler(pipe, tk.READABLE, self.read_pipe)

    def read_pipe(self, pipe, _mask):
        pending, callback = self.streams[pipe]
        try:
            data = os.read(pipe.fileno(), 65536)
        except BlockingIOError:
            return
        if data:
            lines = (pending + data).split(b"\n")
            self.streams[pipe] = lines.pop(), callback
            for line in lines:
                callback(line)
            return
        if pending:
            callback(pending)
        self.root.deletefilehandler(pipe)
        del self.streams[pipe]
        pipe.close()
        if pipe is self.process.stdout:
            self.live_ready = False
            self.manual_button.configure(state="disabled")
            self.input_status.set("Live shot input stopped. See the terminal for details.")

    def receive_status(self, line):
        print(line.decode(errors="replace"), file=sys.stderr)
        if line.startswith(b"V4L2 reports"):
            self.live_ready = True
            self.manual_button.configure(state="normal")
            self.input_status.set("Ready. Roll through L1 → L2.")

    def request_default(self, _event=None):
        if self.game.state == "ready" and str(self.manual_button["state"]) == "normal":
            try:
                self.process.send_signal(signal.SIGUSR1)
            except ProcessLookupError:
                self.manual_button.configure(state="disabled")
                self.input_status.set("Live shot input stopped.")

    def next_shot(self):
        if self.game.state == "rolling":
            return
        self.game.reset()
        self.log_event({"event": "next_shot", "monotonic_s": monotonic()})
        self.shot_status.set("Waiting for a shot")
        self.latency_status.set("")
        if self.replay is not None:
            for line in self.replay:
                if self.receive_shot(line):
                    return
            self.input_status.set("Replay complete.")
        elif self.live_ready:
            self.input_status.set("Ready. Roll through L1 → L2.")

    def stop_live(self):
        for pipe in list(self.streams):
            pipe.close()
        self.streams.clear()
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                os.killpg(self.process.pid, signal.SIGKILL)
                self.process.wait()

    def close(self):
        if self.stop.is_set():
            return
        self.stop.set()
        for pipe in self.streams:
            self.root.deletefilehandler(pipe)
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--course-dir", type=Path, default=LOCAL_COURSE)
    parser.add_argument("--calibration", type=Path, default=HERE / "floor-calibration.json")
    parser.add_argument("--preview", action="store_true", help="Also show the live camera preview")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--replay", type=Path, help="Play saved shot events instead of using live devices")
    source.add_argument("--diagnostics", type=Path, help="Record live input into a new directory")
    args = parser.parse_args()

    if not (args.course_dir / "game_app.py").is_file() or not (args.course_dir / "putting.py").is_file():
        parser.error(f"Could not find the 2D putting course in {args.course_dir}.")
    sys.path.insert(0, str(args.course_dir.resolve()))
    from game_app import PuttingApp
    from putting import PuttingGame

    replay = iter(args.replay.read_bytes().splitlines()) if args.replay else None
    diagnostics = args.diagnostics.resolve() if args.diagnostics else None
    root = tk.Tk()
    shot_log = None
    if diagnostics is not None:
        diagnostics.mkdir()
        shot_log = (diagnostics / "shots.jsonl").open("x", buffering=1)
    try:
        app = CourseWindow(root, PuttingGame(), PuttingApp.animate, replay=replay, shot_log=shot_log)
        signal.signal(signal.SIGTERM, lambda *_: root.after(0, app.close))
        try:
            if replay is None:
                app.start_live(args.calibration.resolve(), args.preview, diagnostics)
            else:
                root.after(350, app.next_shot)
            root.mainloop()
        finally:
            app.stop_live()
    finally:
        if shot_log is not None:
            shot_log.close()


if __name__ == "__main__":
    main()
