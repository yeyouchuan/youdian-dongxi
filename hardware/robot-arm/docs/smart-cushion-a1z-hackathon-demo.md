# Smart Cushion × A1Z hackathon demo design

Updated: 2026-07-23

## Product decision

The competition product is an **office-wellness physical companion**:

> The cushion detects prolonged sitting or pressure asymmetry, the robot
> acknowledges the user, gives a visible reminder, and optionally brings a
> lightweight care object. The system records the intervention and whether the
> user stood up.

The core trigger is **continuous occupancy without a sufficiently long
away interval**, not merely “the cushion has been empty.” The production rule
can remain 45 minutes with a 3-minute away reset. Competition `demo_mode`
compresses the trigger to 10–15 seconds and must label the timer as accelerated.

The cushion remains the source of truth for occupancy, seated duration, and
the supported posture classes:

- `upright`
- `legs_crossed`
- `away`

The wrist camera is used to locate a person, verify the scene, estimate metric
clearance, and confirm whether a prop is present. It does not replace cushion
pressure classification.

## Recommended final demonstration

### Main path: reminder plus prop handoff

1. The participant sits on the cushion.
2. The dashboard changes from `away` to `upright`.
3. The accelerated seated timer reaches its threshold.
4. A1Z moves from `HOME_SAFE` to `WAKE_LOOK`, keeping a non-contact standoff.
5. The robot gives a spoken reminder and performs a short visible gesture.
6. If the participant remains seated, A1Z picks a large, lightweight tagged
   prop from a fixed cradle.
7. It presents the prop at a fixed handoff zone, without chasing the user's
   hand.
8. When the cushion reports `away`, the dashboard marks the intervention as
   successful.
9. A1Z returns to the powered runtime standby pose `HOME_SAFE`.
10. For shutdown, it synchronously interpolates all joints to
    `ZERO_SHUTDOWN = [0, 0, 0, 0, 0, 0]`, verifies the measured pose, keeps
    motors enabled until the operator confirms physical support, and only then
    permits motor disable and 24 V power-off.

Suitable props include a stretch card, an empty plastic cup, or a foam baton.
Do not use glass, hot liquid, a sharp object, or a heavy bottle.

### Short fallback path

If depth, grasping, or the VLA runtime is unavailable:

1. Replay a valid cushion event.
2. Move to `WAKE_LOOK`.
3. Play the reminder.
4. Point toward a printed stretch card fixed on the table.
5. Return to `HOME_SAFE`.

This path must remain fully local and work without internet access.

## Interaction complexity and verifiability

| Interaction | Complexity | Repeatability | Human-contact risk | Competition recommendation |
| --- | --- | --- | --- | --- |
| Voice plus non-contact gesture | Low | Very high | Low | Mandatory fallback |
| Tap a fixed foam target or chair-mounted trigger | Medium | High | Low when the target is outside the body | Best first physical-contact milestone |
| Pick a tagged prop from a fixed cradle and present it | Medium-high | High after calibration | Low with a light prop and fixed handoff zone | Best final main demo |
| Open-vocabulary object pick with VLM/VLA | High | Medium-low without task data | Medium | Stretch goal |
| Tap a mannequin shoulder with force instrumentation | High | Medium | Medium | Simulation/fixture validation only |
| Tap or strike a real person | Very high | Low | High | Not part of the competition main path |

“拍一下” must never mean an uncontrolled strike. The first contact target is
a fixed foam pad, load cell, or chair-mounted pressure switch. Validation must
measure approach speed, contact force, peak joint effort, stopping distance,
and retreat behavior.

## System architecture

```text
Smart-cushion samples or replay
  -> CushionEvent classifier and debounce
  -> competition interaction state machine
  -> RobotIntent
  -> scene/perception gate
       RGB person/prop semantics
       aligned depth and metric clearance
       confidence and timestamp checks
  -> motion primitive planner
  -> strict safety governor
       joint limits, including J4 ±1.309 rad
       velocity/acceleration/jerk limits
       table/self/human clearance
       camera-cable wrist limits
  -> MuJoCo first
  -> separately approved A1Z hardware gate
```

The VLM/VLA never writes CAN commands. It may propose a semantic intent or a
candidate action sequence, but deterministic code must validate and execute
bounded motion primitives.

## Data contracts

```text
CushionEvent
  timestamp_ns
  occupancy: occupied | away
  posture: upright | legs_crossed | null
  confidence: 0..1
  seated_seconds
  pressure_zones
  source: live | replay | demo

SceneObservation
  timestamp_ns
  camera_serial
  rgb_frame_id
  depth_frame_id
  person_present
  prop_class
  prop_pose_camera
  min_depth_m
  confidence
  calibration_version

RobotIntent
  idle | wake_look | remind | tap_fixture | pick_prop | offer_prop | retreat
  issued_at_ns
  expires_at_ns
  reason
  target_id
  demo_mode

MotionResult
  intent
  primitive
  started_at_ns
  completed_at_ns
  success
  reject_reason
  min_clearance_m
  peak_effort
  final_joint_error
```

All commands expire. Missing or stale cushion/camera input must not continue a
motion toward a person.

## Required robot poses and primitives

Do not begin by solving arbitrary end-effector targets online. First record
and verify a small library of named poses and interpolated primitives.

### Named poses

- `HOME_SAFE`: powered runtime standby pose. It is not sufficient for motor
  disable or power-off.
- `ZERO_SHUTDOWN`: official all-zero shutdown pose. Reach it using the
  60-frame, 60 Hz quintic minimum-jerk sequence while control remains active.
- `WAKE_LOOK`: arm raised enough for the wrist camera to see the interaction
  zone while retaining table and cable clearance.
- `TAP_PRE`: tool aligned with the fixed foam target, outside contact distance.
- `TAP_TOUCH_FIXTURE`: a few centimeters beyond `TAP_PRE`, enabled only for a
  force-instrumented fixture.
- `AIR_PICK_PRE`: high pre-grasp pose for the requested empty-space grasp
  rehearsal. It is not a calibrated tabletop-pick pose.
- `PICK_PRE`: above the fixed prop cradle, to be solved only after the table,
  cradle, TCP, and movable gripper are present in the model.
- `PICK`: gripper centered on the known prop grasp region.
- `LIFT`: vertical retreat after grasp.
- `OFFER`: fixed handoff zone outside the participant's body capsule.
- `RETREAT`: collision-free intermediate pose leading back to `HOME_SAFE`.

### Primitive rules

- Move through waypoints; never command a far IK solution in one step.
- Warm-start IK from measured joints.
- Check the swept path, not only waypoint endpoints.
- Keep the strict physical J4 limit of ±1.309 rad.
- Apply a smaller J6 range until the wrist-camera cable has a rigid strain
  relief and its twist envelope is measured.
- A failed grasp retreats upward, opens the gripper over the cradle, and
  returns home.
- Person loss or stale depth freezes approach and selects `RETREAT`.

## Wrist RGB-D camera status

macOS currently enumerates:

- RGB/UVC device: `Dabai DC1`
- RGB serial: `CC1N16200WR`
- RGB USB VID/PID: `11205:1367`
- Separate depth interface: `ORBBEC Depth Sensor`
- Depth USB VID/PID: `11205:1623`
- Verified RGB capture: 1920×1080 at 15 FPS through OpenCV/AVFoundation

The captured RGB view sees a standing person but points upward and does not
show the grasp surface or gripper. It is adequate for a first person-presence
test, not for tabletop grasp verification.

Because the camera moves with the wrist, the coordinate chain is:

```text
T_base_camera(q) = T_base_tool(q) * T_tool_camera
p_base = T_base_camera(q) * p_camera
```

Required before visual motion:

1. Replace tape-only mounting with a rigid bracket.
2. Add cable strain relief on a non-moving wrist link.
3. Measure safe J5/J6 cable twist and bend limits.
4. Read RGB and depth intrinsics from the correct Orbbec SDK generation.
5. Align depth to color and reject invalid/zero depth.
6. Calibrate `T_tool_camera` with multiple arm poses and a fixed board.
7. Validate metric points against a ruler and known tabletop targets.

The DaBai DC1 appears in the legacy Orbbec SDK release notes, while it is not
listed in the current Orbbec SDK v2 supported-device table. Do not blindly
install the v2 Python package and treat device discovery as guaranteed. Verify
the exact SDK generation and firmware first.

## VLM/VLA role

### Suitable first uses

- “Is a person present in the interaction zone?”
- “Is the stretch card or foam cup on its cradle?”
- “Did the participant take the offered prop?”
- Select one of a small set of allowed `RobotIntent` values.
- Produce natural-language explanations for the dashboard.

### Unsuitable first uses

- Direct joint-angle or torque control.
- Estimating metric distance from RGB when depth is available.
- Continuous collision avoidance.
- Deciding contact force.
- Open-ended striking or following a moving body part.

The deterministic RGB-D/geometry pipeline remains responsible for metric
position and clearance. VLA integration is accepted only when its robot,
observation, and action spaces match this A1Z/G1Z setup or an explicit adapter
has been trained and replay-validated.

### Galaxea G0.5 integration decision

The current official G0.5 repository has real-robot clients for R1 Lite,
R1 Pro, SO-100/101, and DROID/Franka, but no A1Z/G1Z client, embodiment
configuration, checkpoint, or deployment contract. The official R1 input also
uses three RGB views rather than the current single wrist camera. Therefore:

- the Mac remains the cushion, camera, state-machine, logging, and safety
  gateway;
- an RTX Linux host is required if G0.5 is demonstrated;
- G0.5 starts in `shadow` mode and may later select an approved intent ID;
- A1Z needs its own observation/action adapter and training statistics before
  continuous VLA actions can be evaluated;
- no G0.5 output bypasses the strict limit and trajectory safety governor.

See
[`galaxea-vla-smart-cushion-integration.md`](research/galaxea-vla-smart-cushion-integration.md)
for the source-level compatibility assessment.

## Current offline pose result

The first coordinated simulation trajectory is:

```text
HOME_SAFE -> WAKE_LOOK -> AIR_PICK_PRE -> LIFT
          -> OFFER -> LIFT -> HOME_SAFE
```

It uses minimum-jerk joint interpolation at a default peak speed of
`0.12 rad/s`, 50 Hz sampling, a `0.08 rad` limit margin, and the physical J4
limit of `±1.309 rad`. The current run produced 2,023 samples over 40.44
seconds with a measured peak joint speed of `0.1200 rad/s`.

`AIR_PICK_PRE` is the highest candidate pose and rehearses reaching toward an
imaginary object in free space. The current vendor URDF has fixed gripper
fingers and no table, prop, camera, cable, force sensor, or calibrated TCP, so
this result validates only joint-limit and trajectory generation—not grasp,
collision, cable, or hardware safety.

## Development stages and gates

### Stage 0 — replayable vertical slice

- Replay `CushionEvent`.
- Drive dashboard and state machine.
- Execute named motions in MuJoCo only.
- Pass 20 consecutive deterministic replays.

### Stage 1 — camera-only perception

- Record RGB and depth without robot motion.
- Validate person presence, prop presence, timestamps, and metric depth.
- Confirm loss/occlusion produces `RETREAT`, not a new approach.

### Stage 2 — empty coordinated hardware trajectory

- Remove people and props from the workspace.
- Use the strict-limit hardware gate.
- Move `HOME_SAFE -> WAKE_LOOK -> AIR_PICK_PRE -> LIFT -> HOME_SAFE`.
- Keep the gripper open.
- Verify camera cable clearance throughout.
- Complete at least 10 runs without limit, feedback, or return failures.

Current status (2026-07-23): the first low-speed hardware segment reached a
measured `WAKE_LOOK`-like pose, but J3 tracking lag made the next high target
exceed the measured 35° segment gate. A defect in the first return
implementation then disabled at the elevated pose; a separate measured-pose
recovery returned near the run baseline but was still not at the official
all-zero shutdown pose, so disabling caused another fall. The runner now uses
adaptive 20° measured-feedback steps plus mandatory 60-frame zero homing and
an operator-support interlock. Stage 2 is therefore **not passed** and must
restart with only `baseline -> WAKE_LOOK -> baseline -> ZERO_SHUTDOWN`.

### Stage 3 — fixed prop pick/place

- Use a large light prop in a mechanical cradle.
- Start with a taught pose or fiducial, not open-vocabulary VLA.
- Validate grasp, lift, presentation, release, and failure retreat.

### Stage 4 — fixed soft-target contact

- Use a load cell or calibrated pressure switch behind a foam target.
- Establish a low-speed contact envelope in MuJoCo and on the fixture.
- Require independent force/effort stop criteria.

### Stage 5 — semantic enhancement

- Add VLM scene verification.
- Evaluate GalaxeaVLA only after its supported embodiment and runtime are
  confirmed.
- Retain deterministic primitives and safety gates as the final executor.

## Acceptance criteria

- Main demo succeeds 10 consecutive times from a powered-on safe pose.
- Offline fallback succeeds without cloud or competition Wi-Fi.
- No real-person contact is needed to complete the judging story.
- All recorded target poses satisfy strict limits with margin.
- Perception timestamps, calibration versions, IK status, minimum clearance,
  peak effort, and return status are logged.
- Any stale input, low confidence, failed IK, unexpected contact, cable limit,
  or control fault freezes approach and retreats when control remains healthy.
- Normal shutdown returns from `HOME_SAFE` to `ZERO_SHUTDOWN` while the
  control loop remains active, verifies every measured joint within 5° of
  zero, keeps zero actively held while the operator confirms the shutdown
  parking posture and physical support, disables motors, and only then permits
  24 V power-off.

Before any further Demo motion, run a standalone shutdown validation:

```text
current pose -> ZERO_SHUTDOWN -> enabled hold -> parking confirmation
             -> operator support -> motor disable
```

After it passes, the Demo requires a fresh normal power-on/enable cycle. The
Demo trajectory then ends with the same zero-homing and parking interlock.

## Immediate next work

1. With the camera still removed, inspect the arm after the fall and run only
   the standalone zero-homing/parking/disable validation.
2. After a fresh power-on cycle, run only
   `baseline -> WAKE_LOOK -> baseline -> ZERO_SHUTDOWN`.
3. Reinstall the camera later using a rigid mount and cable strain relief.
4. Verify the DaBai DC1 depth stream and intrinsics with the compatible Orbbec
   SDK.
5. Add table, camera, cable-envelope, TCP, and movable-gripper proxies to the
   MuJoCo scene, then validate the named trajectory against them.
6. Implement the replayable `CushionEvent -> RobotIntent` state machine and
   pass 20 deterministic replays.
