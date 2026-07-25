# Teach recordings

`a1z_teach/` contains timestamped six-joint plus normalized-gripper feedback
captured on the physical A1Z.

- `*.raw.json`: immutable source feedback, preserved even when validation
  fails.
- `*.smoothed.json`: offline minimum-jerk reconstruction of discontinuous
  position steps.
- other `*.json`: recordings that passed direct limit and speed validation.

Never edit a raw recording in place. Regenerate a derived file with:

```bash
PYTHONPATH=. .venv/bin/python scripts/a1z_safe_teach_and_play.py \
  smooth NAME.raw.json
```

A recording is data, not permission to move hardware. Inspect limits, begin
at half speed, clear the workspace, keep the PSU attended, and use the
supported shutdown interlock.
