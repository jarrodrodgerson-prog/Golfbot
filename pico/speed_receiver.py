"""Receive USB speed events on the Pi and save them to SQLite."""

import argparse
from datetime import datetime, timezone
import json
import sqlite3
import sys
import time


def save_measurement(db, line, receipt):
    try:
        event = json.loads(line)
    except (UnicodeError, ValueError):
        return False
    if not isinstance(event, dict) or event.get("event") != "ball_speed":
        return False

    timestamp = event.get("timestamp_ms")
    elapsed = event.get("elapsed_us")
    spacing = event.get("beam_spacing_m")
    speed = event.get("speed_mph")
    if type(timestamp) is not int or not 0 <= timestamp < 2**63:
        return False
    if type(elapsed) is not int or not 0 < elapsed < 2**63:
        return False
    for value in (spacing, speed):
        if type(value) not in (float, int) or not 0 < value <= sys.float_info.max:
            return False

    with db:
        db.execute(
            """INSERT INTO speed_measurements
               (received_at_utc, timestamp_ms, elapsed_us, beam_spacing_m, speed_mph)
               VALUES (?, ?, ?, ?, ?)""",
            (receipt, timestamp, elapsed, spacing, speed),
        )
    return True


def receive(db, read_line):
    partial = False
    while True:
        line = read_line(4096)
        if not line:
            return
        end_of_line = line.endswith(b"\n")
        if end_of_line and not partial:
            receipt = datetime.now(timezone.utc).isoformat()
            if save_measurement(db, line, receipt):
                print(line.decode("utf-8").strip(), flush=True)
        partial = not end_of_line


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--port", default="/dev/ttyACM0")
    source.add_argument("--stdin", action="store_true", help="Read a Pico runner pipeline")
    parser.add_argument("--database", default="golfbot.sqlite3")
    args = parser.parse_args()

    db = sqlite3.connect(args.database)
    try:
        with db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS speed_measurements (
                    id INTEGER PRIMARY KEY,
                    received_at_utc TEXT NOT NULL,
                    timestamp_ms INTEGER NOT NULL,
                    elapsed_us INTEGER NOT NULL,
                    beam_spacing_m REAL NOT NULL,
                    speed_mph REAL NOT NULL
                )"""
            )
        if args.stdin:
            receive(db, sys.stdin.buffer.readline)
            return

        import serial

        while True:
            try:
                with serial.Serial(args.port, baudrate=115200, exclusive=True) as port:
                    print("Listening on {}".format(args.port), file=sys.stderr)
                    receive(db, lambda size: port.read_until(size=size))
            except serial.SerialException as error:
                print("{}; retrying in 2 seconds".format(error), file=sys.stderr)
                time.sleep(2)
    except KeyboardInterrupt:
        pass
    finally:
        db.close()


if __name__ == "__main__":
    main()
