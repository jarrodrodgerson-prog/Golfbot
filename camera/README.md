# Golfbot camera setup

On the Raspberry Pi 5, install OpenCV and the V4L2 command-line tools.

```bash
sudo apt update
sudo apt install python3-opencv v4l-utils
```

Connect the Dell WB3023 and run these commands from a terminal on the Pi desktop. Close other applications using the webcam first.

```bash
cd /home/jrod/golfbot
v4l2-ctl --device /dev/video0 --list-formats-ext
/usr/bin/python3 camera/ball_tracking.py
```

The app requests MJPG at 1280×720 and 60 FPS and prints the mode reported by V4L2. The video shows the detected center in full-frame pixels, a short trail, and the measured preview processing rate. That rate includes capture, detection, and the display loop. Press **Q** with the preview focused to quit.

Use even lighting and a dark, matte background. Restrict the search to the ball's travel area and tune the expected ball radius if there are other bright objects in view.

```bash
/usr/bin/python3 camera/ball_tracking.py --roi 200 160 880 420 --radius 6 35 --white-min 190
```

The optional ROI uses top-left x and y, width, and height. Adjust the example to match the actual setup. Use `--device` if Linux assigns the webcam a different path.

## Horizontal launch angle

The tracker retains recent frame numbers, host receipt times, centers, and radii. A future angle estimator can map pixel centers into calibrated coordinates on the plane of travel and fit the early trajectory relative to the target line. For airborne shots, validate the camera geometry against out-of-plane motion as well. Host receipt times reflect when frames reach the app. Camera calibration and tracking at real ball speeds are still required before reporting accurate launch angles.
