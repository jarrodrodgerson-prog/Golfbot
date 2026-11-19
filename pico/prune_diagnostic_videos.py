"""List or expire Golfbot AVI recordings in the local Pico workspace."""

import argparse
import stat
import subprocess
import time
from pathlib import Path


def prune(workspace, days, delete):
    cutoff = time.time() - days * 86400
    workspace_device = workspace.stat().st_dev
    videos = list(workspace.glob("*.avi"))
    for pattern in ("course-diagnostic-*", "france-diagnostic-*"):
        videos.extend(
            folder / "preview.avi" for folder in workspace.glob(pattern)
            if not folder.is_symlink() and folder.is_dir()
        )

    for video in sorted(videos):
        try:
            info = video.lstat()
        except FileNotFoundError:
            continue
        if (not stat.S_ISREG(info.st_mode)
                or info.st_dev != workspace_device
                or info.st_mtime >= cutoff
                or video.with_suffix(".avi.keep").exists()):
            continue

        if delete:
            # fuser exits 1 with no output when no process has the file open.
            owners = subprocess.run(
                ["/usr/bin/fuser", str(video)], capture_output=True, check=False,
            )
            if owners.returncode != 1 or owners.stdout or owners.stderr:
                continue
            try:
                current = video.lstat()
                if (current.st_ino, current.st_dev, current.st_mtime_ns) != (
                    info.st_ino, info.st_dev, info.st_mtime_ns
                ) or video.with_suffix(".avi.keep").exists():
                    continue
                video.unlink()
            except FileNotFoundError:
                continue
        print(f"{'Deleted' if delete else 'Would delete'} {video}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", required=True, type=int, help="Days to retain recordings")
    parser.add_argument("--delete", action="store_true", help="Delete eligible videos")
    args = parser.parse_args()
    if args.days <= 0:
        parser.error("--days must be positive")
    prune(Path(__file__).resolve().parent, args.days, args.delete)


if __name__ == "__main__":
    main()
