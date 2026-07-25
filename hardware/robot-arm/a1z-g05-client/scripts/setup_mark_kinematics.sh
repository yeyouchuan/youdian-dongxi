#!/usr/bin/env bash
set -euo pipefail

TARGET="$HOME/.cache/a1z-g05/so101_new_calib.urdf"
SO_ARM_COMMIT="fda892cba81032c46c40976a48c9ceadbf40a9ca"
EXPECTED_SHA256="3a65d2d35e68a8d2f0c2cc176d19b884506543c93ba72980145b80abe276022c"
mkdir -p "$(dirname "$TARGET")"
TMP="$(mktemp "${TARGET}.tmp.XXXXXX")"
trap 'rm -f "$TMP"' EXIT
curl -fL \
  "https://raw.githubusercontent.com/TheRobotStudio/SO-ARM100/${SO_ARM_COMMIT}/Simulation/SO101/so101_new_calib.urdf" \
  -o "$TMP"
printf '%s  %s\n' "$EXPECTED_SHA256" "$TMP" | sha256sum --check --status
mv "$TMP" "$TARGET"
trap - EXIT
echo "Installed official SO101 URDF at $TARGET"

A1Z_URDF="$HOME/GALAXEA-A1Z/a1z/robot_models/a1z/A1Z_G1Z.urdf"
if [[ ! -f "$A1Z_URDF" ]]; then
  echo "Missing A1Z URDF: $A1Z_URDF" >&2
  echo "Clone/bootstrap the pinned GALAXEA-A1Z gripper branch first." >&2
  exit 1
fi
echo "Found A1Z URDF at $A1Z_URDF"
