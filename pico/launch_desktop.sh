#!/usr/bin/env bash
set -eu

cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

game_url='http://127.0.0.1:8765/?mouse=0'

check_device() {
    local device=$1 ownership
    if [[ ! -c "$device" || ! -r "$device" || ! -w "$device" ]]; then
        echo "Cannot access $device." >&2
        return 1
    fi
    if ownership=$(fuser -v "$device" 2>&1) || [[ -n "$ownership" ]]; then
        printf '%s\n' "$ownership" >&2
        echo "Close the application using $device, then try again." >&2
        return 1
    fi
}

open_game_browser() {
    local url=$1
    if command -v chromium >/dev/null; then
        setsid --wait chromium --new-window "$url"
    else
        xdg-open "$url"
    fi
}

start_game() {
    if curl -fsS --max-time 1 "$game_url" >/dev/null 2>&1; then
        open_game_browser "$game_url"
        return
    fi
    check_device "${PICO_PORT:-/dev/ttyACM0}" || return 1
    check_device /dev/video0 || return 1

    (
        for ((attempt = 0; attempt < 20; attempt++)); do
            if curl -fsS --max-time 1 "$game_url" >/dev/null 2>&1; then
                if ! open_game_browser "$game_url"; then
                    echo "Could not open the browser. Open $game_url on the Pi." >&2
                    exit 1
                fi
                exit 0
            fi
            sleep 1
        done
        echo "The browser could not reach the game at $game_url." >&2
    ) &
    local opener=$! game_status=0
    echo "Press Ctrl+C in this terminal to stop TeeOff France."
    /usr/bin/python3 play_france.py || game_status=$?
    kill "$opener" 2>/dev/null || true
    wait "$opener" 2>/dev/null || true
    return "$game_status"
}

start_desktop_game() {
    if curl -fsS --max-time 1 "$game_url" >/dev/null 2>&1; then
        open_game_browser "$game_url"
    else
        systemd-run --user --unit=golfbot-france-live --collect "$PWD/launch_desktop.sh" game
    fi
}

calibrate_camera() (
    check_device /dev/video0 || exit 1
    calibration_dir=$(mktemp -d ./.camera-calibration.XXXXXX) || exit 1
    trap 'rm -rf -- "$calibration_dir"' EXIT
    new_calibration="$calibration_dir/floor-calibration.json"
    /usr/bin/python3 shot_input.py calibrate \
        --width-in 11 --length-in 11 --output "$new_calibration" || exit 1
    if [[ -f "$new_calibration" ]]; then
        mv -- "$new_calibration" floor-calibration.json
    fi
)

case ${1:-} in
    game) action=start_game ;;
    desktop-game) action=start_desktop_game ;;
    calibrate) action=calibrate_camera ;;
    *) echo "Usage: $0 {game|desktop-game|calibrate}" >&2; exit 2 ;;
esac

if "$action"; then
    exit 0
fi
if [[ -t 0 ]]; then
    read -r -p 'Press Enter to close.' || true
fi
exit 1
