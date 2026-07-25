# Galaxy A1Z macOS bring-up

Verified on Apple Silicon macOS on 2026-07-23.

For measured hardware results, aborted tests, and the six-axis startup issue,
read [a1z-test-log-2026-07-23.md](a1z-test-log-2026-07-23.md) before enabling
the arm.

## Reproducible workspace

- `GALAXEA-A1Z/`: upstream `userguide-galaxea/GALAXEA-A1Z` `gripper`
  branch at commit `e931ecd0e25ad35df251097ba42921b3d2fa7224`.
- `.venv/`: local Python 3.12 environment.
- Both are generated locally and intentionally ignored by the parent repo.

Create both from `robot-arm/`:

```bash
PYTHON_BIN="$(brew --prefix python@3.12)/bin/python3.12" ./bootstrap.sh
```

Homebrew system dependencies:

```bash
brew install python@3.12 libusb
```

## Safe USB-CAN detection

The HHS USB-CANFD adapter is not a serial TTY. It will not appear under
`/dev/cu.*`. Its USB identity is `a8fa:8598`.

Run the descriptor-only probe:

```bash
.venv/bin/python scripts/a1z_hhs_probe.py
```

Optionally perform a three-second passive listen at 1 Mbps:

```bash
.venv/bin/python scripts/a1z_hhs_probe.py --listen-seconds 3
```

The probe contains no CAN transmit path and never enables a motor. Receiving
zero frames is expected when the adapter is healthy but the motors are not
broadcasting.

## Current upstream mismatch

An earlier public DimOS A1Z guide described:

```text
dimos/robot/manipulators/galaxea_a1z/scripts/setup_a1z.sh
```

and a macOS PyUSB/gs-usb transport. As of DimOS commit
`10793320a6693b00f82d6f26c7ce77043fa7c6a8`, those files and the documented
`galaxea-a1z` dependency group are not present on the public `main` branch.
The public Galaxea SDK `gripper` branch still hard-codes Linux `socketcan`.

Do not run Linux `can0`, `ip link`, or `modprobe` instructions on macOS. This
repository uses the reviewed `scripts/a1z_hhs_transport.py` integration to
inject a python-can `gs_usb` bus into the vendor SDK.

## Motion gate

The A1Z has no brakes and no independent emergency-stop button. The PSU switch
is the hardware kill switch, and disabling motors can make the arm fall.
Before any active CAN probe or motor enable:

1. Clear people and fragile objects from the entire reachable workspace.
2. Mechanically support the arm against a sudden drop.
3. Keep one operator at the PSU switch.
4. Start with pose readback/hold, low gains, and no contact task.
5. Validate camera coordinates and force limits against a fixture before any
   human interaction.

Do not use a person as the first force-feedback target.

## Mandatory normal shutdown

Returning only to the pose captured at the start of a test is not sufficient.
The runner must reach its explicitly validated shutdown target while the
control loop and 24 V supply are still active. Most diagnostic runners use
the all-zero joint pose. The official-dance wrapper uses the official compact
home pose `[0, 60, -60, 0, 0, 0]°`, which was separately validated by the
continuous bow test and keeps the arm's mass closer to the base.

All local hardware runners use `scripts/a1z_safe_shutdown.py`:

1. Read the current six-axis pose.
2. In the main thread, send exactly 60 joint-position frames at 60 Hz using
   the quintic minimum-jerk polynomial `10t³ - 15t⁴ + 6t⁵`.
3. Continue holding the selected target until every measured joint is within
   5° of that target.
4. Keep motors enabled and block at the terminal.
5. While the selected shutdown target remains actively held, confirm the
   shutdown parking posture.
6. The operator physically supports the arm and types `PARKED_SUPPORTED`.
7. Only then does the runner call `robot.stop()`.
8. The operator may switch off 24 V only after confirming physical stability.

The shutdown-only validation and the Demo are separate powered sessions:

```text
Round A:
current pose -> validated shutdown target -> enabled hold -> confirmation
             -> operator support -> motor disable

Round B:
24 V on -> driver initialization -> motor enable -> preflight
        -> Demo trajectory -> validated shutdown target -> enabled hold
        -> parking confirmation -> operator support -> motor disable
```

A Demo trajectory cannot run after motor disable without a new power-on and
enable sequence.

`robot.stop()` is motor disable, not a harmless software cleanup call. If
power or the control loop is already lost, software cannot home the arm; the
operator must support it immediately.
