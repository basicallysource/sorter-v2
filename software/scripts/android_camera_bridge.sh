#!/usr/bin/env bash

set -euo pipefail

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-18081}"
PATH_SUFFIX="${PATH_SUFFIX:-carousel.mjpg}"
CAMERA_ID="${CAMERA_ID:-0}"
CAMERA_SIZE="${CAMERA_SIZE:-1920x1080}"
CAMERA_FPS="${CAMERA_FPS:-30}"
OUTPUT_FPS="${OUTPUT_FPS:-12}"
OUTPUT_WIDTH="${OUTPUT_WIDTH:-960}"
ANDROID_SERIAL_INPUT="${ANDROID_SERIAL:-${1:-}}"

RUNTIME_DIR="/tmp/lego-sorter-android-camera-${PORT}"
PIPE_PATH="${RUNTIME_DIR}/camera.mkv"
SCRCPY_LOG="${RUNTIME_DIR}/scrcpy.log"
FFMPEG_LOG="${RUNTIME_DIR}/ffmpeg.log"
SCRCPY_PID=""
FFMPEG_PID=""

require_cmd() {
	if ! command -v "$1" >/dev/null 2>&1; then
		echo "Missing required command: $1" >&2
		exit 1
	fi
}

pick_default_device() {
	adb devices | awk '/\tdevice$/{print $1; exit}'
}

cleanup_children() {
	if [ -n "$SCRCPY_PID" ]; then
		kill "$SCRCPY_PID" >/dev/null 2>&1 || true
		wait "$SCRCPY_PID" 2>/dev/null || true
		SCRCPY_PID=""
	fi
	if [ -n "$FFMPEG_PID" ]; then
		kill "$FFMPEG_PID" >/dev/null 2>&1 || true
		wait "$FFMPEG_PID" 2>/dev/null || true
		FFMPEG_PID=""
	fi
	rm -f "$PIPE_PATH"
}

cleanup() {
	cleanup_children
}

trap cleanup EXIT INT TERM

wait_for_child_exit() {
	while true; do
		if [ -n "$FFMPEG_PID" ] && ! kill -0 "$FFMPEG_PID" >/dev/null 2>&1; then
			wait "$FFMPEG_PID" 2>/dev/null || true
			return
		fi
		if [ -n "$SCRCPY_PID" ] && ! kill -0 "$SCRCPY_PID" >/dev/null 2>&1; then
			wait "$SCRCPY_PID" 2>/dev/null || true
			return
		fi
		sleep 1
	done
}

require_cmd adb
require_cmd scrcpy
require_cmd ffmpeg

ANDROID_SERIAL_RESOLVED="$ANDROID_SERIAL_INPUT"
if [ -z "$ANDROID_SERIAL_RESOLVED" ]; then
	ANDROID_SERIAL_RESOLVED="$(pick_default_device)"
fi

if [ -z "$ANDROID_SERIAL_RESOLVED" ]; then
	echo "No Android device found via adb." >&2
	exit 1
fi

mkdir -p "$RUNTIME_DIR"

echo "Starting Android camera bridge"
echo "  device: ${ANDROID_SERIAL_RESOLVED}"
echo "  camera: ${CAMERA_ID}"
echo "  stream: http://${HOST}:${PORT}/${PATH_SUFFIX}"
echo "  logs:   ${SCRCPY_LOG} / ${FFMPEG_LOG}"

while true; do
	cleanup_children
	mkfifo "$PIPE_PATH"

	ffmpeg \
		-hide_banner \
		-loglevel error \
		-fflags nobuffer \
		-flags low_delay \
		-i "$PIPE_PATH" \
		-an \
		-vf "fps=${OUTPUT_FPS},scale=${OUTPUT_WIDTH}:-1" \
		-q:v 7 \
		-f mpjpeg \
		-listen 1 \
		"http://${HOST}:${PORT}/${PATH_SUFFIX}" \
		>"$FFMPEG_LOG" 2>&1 &
	FFMPEG_PID=$!

	sleep 1

	scrcpy \
		-s "$ANDROID_SERIAL_RESOLVED" \
		--video-source=camera \
		--camera-id="$CAMERA_ID" \
		--camera-size="$CAMERA_SIZE" \
		--camera-fps="$CAMERA_FPS" \
		--no-audio \
		--no-playback \
		--no-control \
		--record-format=mkv \
		--record="$PIPE_PATH" \
		>"$SCRCPY_LOG" 2>&1 &
	SCRCPY_PID=$!

	wait_for_child_exit
	echo "Android camera bridge restarted."
	sleep 1
done
