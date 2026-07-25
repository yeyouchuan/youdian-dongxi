#!/usr/bin/env bash
set -euo pipefail

MARK_SSH_HOST="${MARK_SSH_HOST:-mark}"

echo "Requesting the A1Z safe stop before shutting down network services"
if ! ssh -o BatchMode=yes -o ConnectTimeout=5 "${MARK_SSH_HOST}" '
  if test -S /tmp/a1z.sock; then
    "$HOME/GALAXEA-A1Z/.venv/bin/python" \
      "$HOME/GALAXEA-A1Z/tools/a1zctl" stop
  else
    echo "A1Z socket is already absent"
  fi
'; then
  echo "Cannot confirm A1Z safe stop; leaving demo services running" >&2
  exit 2
fi

stop_screen() {
  local name="$1"
  local session
  session="$(screen -list 2>/dev/null | awk -v suffix=".${name}" '$1 ~ suffix "$" {print $1; exit}')"
  if [[ -n "${session}" ]]; then
    echo "Stopping screen session ${session}"
    screen -S "${session}" -X quit
  fi
}

# The first name is the preferred single-session supervisor. The remaining
# names support the split sessions used during development and recovery.
stop_screen cushion-live
stop_screen cushion-mqtt-live
stop_screen cushion-lan-broker
stop_screen g05-policy-relay

echo "Demo services stopped. It is now safe to power off the A1Z controller."
