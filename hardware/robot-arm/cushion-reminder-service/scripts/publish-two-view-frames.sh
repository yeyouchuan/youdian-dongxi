#!/usr/bin/env bash
set -euo pipefail

service_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mark_host="${MARK_SSH_HOST:-mark}"
api_base="${CAMERA_API_BASE:-http://127.0.0.1:3000}"
interval_seconds="${CAMERA_PUBLISH_INTERVAL_SECONDS:-1}"
task_temp="$(mktemp -d)"

cleanup() {
  rm -rf "${task_temp}"
}
trap cleanup EXIT INT TERM

ssh -o BatchMode=yes "${mark_host}" "mkdir -p /tmp/a1z-vision"

publish_jpeg() {
  local view="$1"
  local source="$2"
  local orientation="$3"
  local path="$4"
  curl --fail --silent --show-error \
    -X POST "${api_base}/api/cameras/${view}/frame" \
    -H "Content-Type: image/jpeg" \
    -H "X-Camera-Source: ${source}" \
    -H "X-Orientation-Degrees: ${orientation}" \
    --data-binary "@${path}" >/dev/null
}

while true; do
  if right_device=$(ssh -o BatchMode=yes "${mark_host}" '
    set -eu
    selected=""
    for node in /dev/video*; do
      properties=$(udevadm info --query=property --name="$node" 2>/dev/null || true)
      case "$properties" in
        *"ID_VENDOR_ID=0408"*"ID_MODEL_ID=30c3"*)
          if v4l2-ctl -d "$node" --list-formats-ext 2>/dev/null | grep -q "MJPG"; then
            selected="$node"
            break
          fi
          ;;
      esac
    done
    test -n "$selected"
    next=/tmp/a1z-vision/exterior-right.next.jpg
    timeout 12 v4l2-ctl -d "$selected" \
      --set-fmt-video=width=640,height=480,pixelformat=MJPG \
      --set-parm=30 --stream-mmap=4 --stream-skip=2 --stream-count=1 \
      --stream-to="$next" --stream-poll >/dev/null 2>&1
    mv "$next" /tmp/a1z-vision/exterior-right.jpg
    printf "%s" "$selected"
  '); then
    right_frame="${task_temp}/mark-right.jpg"
    scp -q "${mark_host}:/tmp/a1z-vision/exterior-right.jpg" "${right_frame}"
    publish_jpeg \
      "exterior_right" "mark-wsl-uvc-0408:30c3:${right_device}" "0" "${right_frame}"
  else
    echo "Mark right camera 0408:30c3 did not produce a fresh MJPEG frame" >&2
  fi

  if [[ "${CAMERA_PUBLISH_ONCE:-0}" == "1" ]]; then
    break
  fi
  sleep "${interval_seconds}"
done
