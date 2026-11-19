"""Receive USB speed events on the Pi and save them to SQLite."""

import argparse
from datetime import datetime, timezone
import json
import sqlite3
import sys
import time


def parse_measurement(line):
    try:
        event = json.loads(line)
    except (UnicodeError, ValueError):
        return None
    if not isinstance(event, dict) or event.get("event") != "ball_speed":
        return None

    timestamp = event.get("timestamp_ms")
    elapsed = event.get("elapsed_us")
    spacing = event.get("beam_spacing_m")
    speed = event.get("speed_mph")
    if type(timestamp) is not int or not 0 <= timestamp < 2**63:
        return None
    if type(elapsed) is not int or not 0 < elapsed < 2**63:
        return None
    for value in (spacing, speed):
        if type(value) not in (float, int) or not 0 < value <= sys.float_info.max:
            return None

    return event


def store_measurement(db, event, receipt):
    with db:
        db.execute(
            """INSERT INTO speed_measurements
               (received_at_utc, timestamp_ms, elapsed_us, beam_spacing_m, speed_mph)
               VALUES (?, ?, ?, ?, ?)""",
            (receipt, event["timestamp_ms"], event["elapsed_us"],
             event["beam_spacing_m"], event["speed_mph"]),
        )


def save_measurement(db, line, receipt):
    event = parse_measurement(line)
    if event is None:
        return False
    store_measurement(db, event, receipt)
    return True


def open_database(path):
    db = sqlite3.connect(path)
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
    except sqlite3.Error:
        db.close()
        raise
    return db


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

    db = open_database(args.database)
    try:
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
