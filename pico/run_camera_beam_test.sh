#!/usr/bin/env bash
set -eu

if [[ ${1:-} == --help || ${1:-} == -h ]]; then
    echo "Usage: ./run_camera_beam_test.sh [--speed | --game CALIBRATION.json] [camera tracker options]"
    echo "Set PICO_PORT to override /dev/ttyACM0 or MPREMOTE to select mpremote."
    exit 0
fi

speed_mode=false
calibration=
case ${1:-} in
    --game)
        if [[ $# -lt 2 || ! -r "$2" ]]; then
            echo "Game mode needs a readable calibration JSON file." >&2
            exit 1
        fi
        speed_mode=true
        calibration=$2
        shift 2
        ;;
    --speed)
        speed_mode=true
        shift
        ;;
esac

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
port=$(realpath -m -- "${PICO_PORT:-/dev/ttyACM0}")
mpremote=${MPREMOTE:-mpremote}
if [[ -z ${MPREMOTE:-} && -x "$HOME/.venvs/golfbot/bin/mpremote" ]]; then
    mpremote=$HOME/.venvs/golfbot/bin/mpremote
fi

if ! command -v "$mpremote" >/dev/null; then
    echo "Install mpremote using the commands in PROJECT_CONTEXT.md." >&2
    exit 1
fi
if [[ ! -c "$port" || ! -r "$port" || ! -w "$port" ]]; then
    echo "Cannot access Pico serial port $port." >&2
    exit 1
fi
if ! command -v fuser >/dev/null; then
    echo "Install fuser (the psmisc package) to check serial ownership." >&2
    exit 1
fi
if ownership=$(fuser -v "$port" 2>&1) || [[ -n "$ownership" ]]; then
    printf '%s\n' "$ownership" >&2
    echo "Could not confirm $port is free. Close MicroPico or any serial monitor first." >&2
    exit 1
fi

camera_pid=
beam_pid=
logger_pid=
fifo_dir=
cleanup() {
    trap ':' INT TERM USR1
    if [[ -n "$camera_pid" ]]; then
        kill "$camera_pid" 2>/dev/null || true
        wait "$camera_pid" 2>/dev/null || true
    fi
    if [[ -n "$beam_pid" ]]; then
        kill "$beam_pid" 2>/dev/null || true
        wait "$beam_pid" 2>/dev/null || true
        # Re-enter raw REPL to interrupt the script still running on the Pico.
        if ! timeout 5s "$mpremote" connect "$port" resume exec "pass" >&2; then
            echo "Could not stop the Pico test. Reconnect in MicroPico and press Ctrl+C." >&2
        fi
    fi
    if [[ -n "$logger_pid" ]]; then
        if [[ -z "$beam_pid" ]]; then
            kill "$logger_pid" 2>/dev/null || true
        fi
        wait "$logger_pid" || true
    fi
    if [[ -n "$fifo_dir" ]]; then
        rm -f -- "$fifo_dir/events"
        rmdir -- "$fifo_dir"
    fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if "$speed_mode"; then
    fifo_dir=$(mktemp -d)
    mkfifo "$fifo_dir/events"
    echo "Keep both beams clear, then roll through L1 → L2." >&2
else
    echo "Keep both beams clear until the Pico prints its baselines." >&2
fi
echo "Press Ctrl+C to stop, or Q if the preview is open." >&2

if [[ -n "$calibration" ]]; then
    game_signal=false
    forward_manual_shot() {
        game_signal=true
        if [[ -n "$camera_pid" ]]; then
            kill -USR1 "$camera_pid" 2>/dev/null || true
        fi
    }
    trap forward_manual_shot USR1
    echo "If a roll is missed, press D in the preview to request a default shot." >&2
    /usr/bin/python3 -u "$script_dir/shot_input.py" --calibration "$calibration" \
        --database "$script_dir/golfbot.sqlite3" "$@" < "$fifo_dir/events" &
    camera_pid=$!
else
    /usr/bin/python3 -u "$script_dir/../camera/ball_tracking.py" --saturation-max 110 "$@" &
    camera_pid=$!
    if "$speed_mode"; then
        /usr/bin/python3 -u "$script_dir/speed_receiver.py" --stdin \
            --database "$script_dir/golfbot.sqlite3" < "$fifo_dir/events" &
        logger_pid=$!
    fi
fi

if "$speed_mode"; then
    PYTHONUNBUFFERED=1 "$mpremote" connect "$port" run "$script_dir/speed_sensor.py" \
        > "$fifo_dir/events" &
else
    PYTHONUNBUFFERED=1 "$mpremote" connect "$port" run "$script_dir/dual_sensor_test.py" &
fi
beam_pid=$!

workers=("$camera_pid" "$beam_pid")
if [[ -n "$logger_pid" ]]; then
    workers+=("$logger_pid")
fi
while true; do
    game_signal=false
    status=0
    wait -n -p finished_pid "${workers[@]}" || status=$?
    if ! "$game_signal" || [[ -n "${finished_pid:-}" ]]; then
        break
    fi
done
if [[ -n "$calibration" && "${finished_pid:-}" == "$beam_pid" ]]; then
    # The shot reader can finish matching events already in the pipe after EOF.
    while true; do
        game_signal=false
        camera_status=0
        wait "$camera_pid" || camera_status=$?
        if ! "$game_signal" || (( camera_status <= 128 )); then
            break
        fi
    done
    camera_pid=
    if [[ $status == 0 ]]; then
        status=$camera_status
    fi
fi
exit "$status"
