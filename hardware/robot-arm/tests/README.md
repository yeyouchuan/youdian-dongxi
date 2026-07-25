# Tests

These are offline unit and regression tests. They use fake robot objects and
do not open CAN or enable motors.

From `robot-arm/`:

```bash
PYTHONPATH=. .venv/bin/pytest -q tests
```

Hardware success is logged separately in
[`../docs/a1z-test-log-2026-07-23.md`](../docs/a1z-test-log-2026-07-23.md);
passing unit tests never authorizes a physical trajectory.
