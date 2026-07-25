"""Bounded GPT correction plans and A1Z actuator-tool adapters."""

from __future__ import annotations

import base64
import json
import math
import os
import shlex
import subprocess
import threading
from enum import Enum
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .vision import REQUIRED_MANIPULATION_VIEWS, CameraView, ObservationSet

MAX_PLAN_STEPS = 4
MAX_DELTA_COMPONENT_M = 0.02
MAX_DELTA_NORM_M = 0.03
MAX_TOOL_SPEED = 0.1


class ToolAction(str, Enum):
    MOVE_TOOL_DELTA = "move_tool_delta"
    SET_GRIPPER = "set_gripper"


class TargetCandidate(str, Enum):
    LEFT_HAND_MODEL = "left_hand_model"
    CENTER_HAND_MODEL = "center_hand_model"
    RIGHT_HAND_MODEL = "right_hand_model"
    SMALL_CARD = "small_card"


TARGET_DESCRIPTIONS = {
    TargetCandidate.LEFT_HAND_MODEL: "leftmost white hand model",
    TargetCandidate.CENTER_HAND_MODEL: "center white hand model",
    TargetCandidate.RIGHT_HAND_MODEL: "rightmost white hand model",
    TargetCandidate.SMALL_CARD: "small flat printed card",
}


def _validate_rigid_matrix(matrix: object, *, label: str) -> list[list[float]]:
    if (
        not isinstance(matrix, list)
        or len(matrix) != 4
        or any(not isinstance(row, list) or len(row) != 4 for row in matrix)
    ):
        raise ValueError(f"{label} must be a 4x4 matrix")
    if not all(
        isinstance(value, (int, float)) and math.isfinite(float(value))
        for row in matrix
        for value in row
    ):
        raise ValueError(f"{label} must contain finite values")
    normalized = [[float(value) for value in row] for row in matrix]
    if any(abs(value) > 1e-6 for value in normalized[3][:3]) or not math.isclose(
        normalized[3][3],
        1.0,
        abs_tol=1e-6,
    ):
        raise ValueError(f"{label} must have homogeneous bottom row")
    rotation = [row[:3] for row in normalized[:3]]
    for column_a in range(3):
        for column_b in range(3):
            dot = sum(
                rotation[row][column_a] * rotation[row][column_b]
                for row in range(3)
            )
            expected = 1.0 if column_a == column_b else 0.0
            if not math.isclose(dot, expected, abs_tol=1e-5):
                raise ValueError(f"{label} rotation must be orthonormal")
    determinant = (
        rotation[0][0]
        * (rotation[1][1] * rotation[2][2] - rotation[1][2] * rotation[2][1])
        - rotation[0][1]
        * (rotation[1][0] * rotation[2][2] - rotation[1][2] * rotation[2][0])
        + rotation[0][2]
        * (rotation[1][0] * rotation[2][1] - rotation[1][1] * rotation[2][0])
    )
    if not math.isclose(determinant, 1.0, abs_tol=1e-5):
        raise ValueError(f"{label} rotation determinant must be +1")
    return normalized


def _matmul_4x4(
    left: list[list[float]],
    right: list[list[float]],
) -> list[list[float]]:
    return [
        [
            sum(left[row][inner] * right[inner][column] for inner in range(4))
            for column in range(4)
        ]
        for row in range(4)
    ]


class CameraIntrinsics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    width: int = Field(ge=1, le=8192)
    height: int = Field(ge=1, le=8192)
    fx: float = Field(gt=0, le=20000)
    fy: float = Field(gt=0, le=20000)
    cx: float = Field(ge=0)
    cy: float = Field(ge=0)

    @model_validator(mode="after")
    def validate_principal_point(self) -> CameraIntrinsics:
        if self.cx >= self.width or self.cy >= self.height:
            raise ValueError("camera principal point must lie inside the image")
        return self


class CameraExtrinsics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parent_frame: Literal["a1z_base", "arm_link6"]
    parent_from_camera: list[list[float]]
    intrinsics: CameraIntrinsics
    orientation_degrees: Literal[0, 90, 180, 270]
    reprojection_error_px: float = Field(ge=0, le=5)

    @model_validator(mode="after")
    def validate_rigid_transform(self) -> CameraExtrinsics:
        self.parent_from_camera = _validate_rigid_matrix(
            self.parent_from_camera,
            label="parent_from_camera",
        )
        return self


class CameraGeometry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    calibration_id: str = Field(min_length=1, max_length=128)
    coordinate_frame: Literal["a1z_base"]
    views: dict[CameraView, CameraExtrinsics]

    @model_validator(mode="after")
    def validate_two_views(self) -> CameraGeometry:
        if set(self.views) != set(REQUIRED_MANIPULATION_VIEWS):
            raise ValueError("camera geometry must contain exactly two required views")
        if self.views[CameraView.EXTERIOR_RIGHT].parent_frame != "a1z_base":
            raise ValueError("exterior_right parent_frame must be a1z_base")
        if self.views[CameraView.WRIST].parent_frame != "arm_link6":
            raise ValueError("wrist parent_frame must be arm_link6")
        return self

    def resolve(self, current_state: dict[str, object]) -> dict[str, object]:
        base_from_tool = _validate_rigid_matrix(
            current_state.get("base_from_tool"),
            label="current_state.base_from_tool",
        )
        resolved_views: dict[str, object] = {}
        for view in REQUIRED_MANIPULATION_VIEWS:
            calibration = self.views[view]
            base_from_camera = calibration.parent_from_camera
            if calibration.parent_frame == "arm_link6":
                base_from_camera = _matmul_4x4(
                    base_from_tool,
                    calibration.parent_from_camera,
                )
            resolved_views[view.value] = {
                "base_from_camera": base_from_camera,
                "intrinsics": calibration.intrinsics.model_dump(mode="json"),
                "orientation_degrees": calibration.orientation_degrees,
                "reprojection_error_px": calibration.reprojection_error_px,
            }
        return {
            "calibration_id": self.calibration_id,
            "coordinate_frame": self.coordinate_frame,
            "views": resolved_views,
        }


class CorrectionStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: ToolAction
    delta_m: tuple[float, float, float] | None
    gripper: float | None = Field(default=None, ge=0, le=1)
    speed: float = Field(gt=0, le=MAX_TOOL_SPEED)
    reason: str = Field(min_length=1, max_length=240)

    @model_validator(mode="after")
    def validate_action_fields(self) -> CorrectionStep:
        if self.action is ToolAction.MOVE_TOOL_DELTA:
            if self.delta_m is None or self.gripper is not None:
                raise ValueError("move_tool_delta requires delta_m and no gripper value")
            if not all(math.isfinite(value) for value in self.delta_m):
                raise ValueError("delta_m must be finite")
            if any(abs(value) > MAX_DELTA_COMPONENT_M for value in self.delta_m):
                raise ValueError("delta_m component exceeds 20 mm")
            norm = math.sqrt(sum(value * value for value in self.delta_m))
            if not 0 < norm <= MAX_DELTA_NORM_M:
                raise ValueError("delta_m norm must be in (0, 30] mm")
        elif self.delta_m is not None or self.gripper is None:
            raise ValueError("set_gripper requires gripper and no delta_m")
        return self


class SceneAssessment(BaseModel):
    """Action-free semantic gate that fixes one target before any motion."""

    model_config = ConfigDict(extra="forbid")

    approved: bool
    selected_target: TargetCandidate | None
    target_visible_views: list[CameraView] = Field(max_length=2)
    gripper_visible_views: list[CameraView] = Field(max_length=2)
    person_in_robot_zone: bool
    safe_to_search: bool = False
    feedback: str = Field(min_length=1, max_length=500)

    @model_validator(mode="before")
    @classmethod
    def discard_target_from_rejected_assessment(cls, data: object) -> object:
        if isinstance(data, dict) and data.get("approved") is False:
            data = dict(data)
            data["selected_target"] = None
        return data

    @property
    def target_description(self) -> str:
        if self.selected_target is None:
            raise RuntimeError("scene assessment has no selected target")
        return TARGET_DESCRIPTIONS[self.selected_target]

    @model_validator(mode="after")
    def validate_scene_gate(self) -> SceneAssessment:
        target_views = set(self.target_visible_views)
        gripper_views = set(self.gripper_visible_views)
        if self.approved:
            if self.selected_target is None:
                raise ValueError("approved assessment requires selected_target")
            if self.person_in_robot_zone:
                raise ValueError(
                    "approved assessment cannot include a person in the robot zone"
                )
            if self.safe_to_search:
                raise ValueError("approved assessment must not request a search sweep")
            if not target_views:
                raise ValueError(
                    "approved assessment requires the target in at least one view"
                )
            if not target_views.intersection(gripper_views):
                raise ValueError(
                    "approved assessment requires target and gripper in a shared view"
                )
        else:
            if self.selected_target is not None:
                raise ValueError("unapproved assessment must not select a target")
            if self.safe_to_search and self.person_in_robot_zone:
                raise ValueError("search sweep cannot be safe while a person is in the zone")
        return self


class CorrectionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approved: bool
    coordinate_frame: Literal["a1z_base"]
    selected_target: TargetCandidate | None
    target_visible_views: list[CameraView] = Field(max_length=2)
    gripper_visible_views: list[CameraView] = Field(max_length=2)
    person_in_robot_zone: bool
    steps: list[CorrectionStep] = Field(max_length=MAX_PLAN_STEPS)
    feedback: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_scene_gate(self) -> CorrectionPlan:
        target_views = set(self.target_visible_views)
        gripper_views = set(self.gripper_visible_views)
        required = set(REQUIRED_MANIPULATION_VIEWS)
        if self.approved:
            if self.selected_target is None:
                raise ValueError("approved plan requires selected_target")
            if self.person_in_robot_zone:
                raise ValueError("approved plan cannot include a person in the robot zone")
            if target_views != required or gripper_views != required:
                raise ValueError(
                    "approved plan requires target and gripper in both views"
                )
            if not self.steps:
                raise ValueError("approved plan must contain at least one step")
        else:
            if self.selected_target is not None:
                raise ValueError("unapproved plan must not select a target")
            if self.steps:
                raise ValueError("unapproved plan must not contain actuator steps")
        return self


class ResponsesClient(Protocol):
    class Responses(Protocol):
        def parse(self, **kwargs: object) -> object: ...

    responses: Responses


_SCENE_ASSESSMENT_SYSTEM_PROMPT = """You are the conservative scene gate for a physical
Galaxea A1Z robot arm. You receive exactly two current JPEG views named exterior_right
and wrist. exterior_right is the fixed Mark laptop camera opposite the gripper. wrist is
the DaBai camera fixed to and moving with the gripper; the gripper tips appear at the
bottom of its correctly oriented image. The long black structures entering from the top
or sides of exterior_right and from the bottom corners of wrist are the robot's two
gripper fingers, not human limbs. Seated people in the distant background are outside the
robot zone; person_in_robot_zone is true only for a real body part over the tabletop
target/approach area. The white hand-shaped objects lying on the table are inert plastic
test models from the target allowlist, not human hands or body parts.

Choose exactly one target from the allowlist: left_hand_model, center_hand_model,
right_hand_model, or small_card. Fail closed. approved may be true only when that same
target and both gripper fingertips are clearly visible together in at least one view and
no person or body part is inside the robot work zone. Both fresh views must still be
examined for people and contradictory evidence, but the fixed exterior camera may be
occluded by the robot base and does not need to show the target when wrist clearly shows
the target and fingertips. If neither view provides shared target-and-gripper evidence,
or the target is ambiguous, approved must be false and selected_target must be null. This
assessment cannot contain or propose any robot action.

safe_to_search is a separate bounded-motion authorization. Set it true only when approved
is false, both views are fresh and unambiguous, no person or body part is in the robot
zone, and one small high-clearance wrist-camera sweep can safely improve target coverage.
Set it false for occlusion, contradictory evidence, uncertain human proximity, stale
views, or any scene where moving without a fixed target would be unsafe."""


_PLANNER_SYSTEM_PROMPT = """You are the conservative correction planner for a physical
Galaxea A1Z robot arm. You receive exactly two current JPEG views named exterior_right
and wrist plus a calibrated camera-geometry description. exterior_right is fixed opposite
the gripper. wrist is the DaBai camera fixed to and moving with the gripper; the gripper
tips appear at the bottom of its correctly oriented image. The long black structures
entering from the top or sides of exterior_right and from the bottom corners of wrist are
the robot's two gripper fingers, not human limbs. Seated people in the distant background
are outside the robot zone; reject only when a real body part overlaps the tabletop
target/approach area. The white hand-shaped objects lying on the table are inert plastic
test models from the target allowlist, not human hands or body parts.

The user message names one allowlisted selected_target. Never switch targets. Fail closed.
approved may be true only when that selected target and both gripper fingertips are visible
in both views and no person or body part is inside the robot work zone. If either view is
pointed elsewhere, occluded, stale-looking, ambiguous, or shows a different target,
approved must be false, selected_target must be null, and steps must be empty.

When approved, output at most four actions. A move_tool_delta is a translation in the A1Z
base frame in metres, limited to 20 mm per axis and 30 mm total. Keep the gripper open while
approaching. Close it only after visible alignment. Use set_gripper values in [0, 1], where
0 is closed and 1 is open. Do not output joint angles, CAN frames, shell commands, or any
unstructured robot instruction. Every action will be measured and re-observed before another
plan is accepted."""


class OpenAICorrectionPlanner:
    """GPT-5.6 planner that can emit only schema-bounded actuator steps."""

    def __init__(
        self,
        *,
        camera_geometry: CameraGeometry | str | None = None,
        client: ResponsesClient | None = None,
        model: str | None = None,
        detail: str | None = None,
        reasoning_effort: str | None = None,
    ) -> None:
        if camera_geometry is None:
            parsed_geometry = None
        elif isinstance(camera_geometry, CameraGeometry):
            parsed_geometry = camera_geometry
        else:
            if not camera_geometry.strip():
                raise ValueError("calibrated camera geometry is required")
            parsed_geometry = CameraGeometry.model_validate_json(camera_geometry)
        self.camera_geometry = parsed_geometry
        self._client = client
        self.model = model or os.environ.get("OPENAI_VISION_MODEL", "gpt-5.6")
        self.detail = detail or os.environ.get("OPENAI_VISION_DETAIL", "original")
        self.reasoning_effort = reasoning_effort or os.environ.get(
            "OPENAI_VISION_REASONING_EFFORT",
            "medium",
        )

    def _get_client(self) -> ResponsesClient:
        if self._client is not None:
            return self._client
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("OpenAI dependency is missing") from exc
        if not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is required for GPT correction planning")
        self._client = OpenAI()
        return self._client

    def plan(
        self,
        *,
        task: str,
        selected_target: TargetCandidate,
        observation: ObservationSet,
        current_state: dict[str, object],
    ) -> CorrectionPlan:
        if self.camera_geometry is None:
            raise RuntimeError("calibrated camera geometry is required for actuator planning")
        resolved_geometry = self.camera_geometry.resolve(current_state)
        content: list[dict[str, str]] = [
            {
                "type": "input_text",
                "text": (
                    f"Task: {task}\n"
                    f"Selected target: {selected_target.value} "
                    f"({TARGET_DESCRIPTIONS[selected_target]})\n"
                    "Resolved camera geometry at this measured robot state: "
                    f"{json.dumps(resolved_geometry, sort_keys=True)}\n"
                    f"Measured robot state: {json.dumps(current_state, sort_keys=True)}"
                ),
            }
        ]
        for view in REQUIRED_MANIPULATION_VIEWS:
            frame = observation.frames[CameraView(view)]
            content.append(
                {
                    "type": "input_text",
                    "text": (
                        f"view={view.value} source={frame.source} "
                        f"orientation_clockwise={frame.orientation_degrees}"
                    ),
                }
            )
            encoded = base64.b64encode(frame.jpeg).decode("ascii")
            content.append(
                {
                    "type": "input_image",
                    "image_url": f"data:image/jpeg;base64,{encoded}",
                    "detail": self.detail,
                }
            )
        response = self._get_client().responses.parse(
            model=self.model,
            reasoning={"effort": self.reasoning_effort},
            input=[
                {"role": "system", "content": _PLANNER_SYSTEM_PROMPT},
                {"role": "user", "content": content},
            ],
            text_format=CorrectionPlan,
        )
        parsed = getattr(response, "output_parsed", None)
        if parsed is None:
            raise RuntimeError("GPT correction planner returned no structured plan")
        if isinstance(parsed, CorrectionPlan):
            return parsed
        return CorrectionPlan.model_validate(parsed)

    def assess_scene(
        self,
        *,
        task: str,
        observation: ObservationSet,
    ) -> SceneAssessment:
        content: list[dict[str, str]] = [
            {
                "type": "input_text",
                "text": (
                    f"Task: {task}\n"
                    "Select one visible allowlisted target and assess the scene."
                ),
            }
        ]
        for view in REQUIRED_MANIPULATION_VIEWS:
            frame = observation.frames[CameraView(view)]
            content.append(
                {
                    "type": "input_text",
                    "text": (
                        f"view={view.value} source={frame.source} "
                        f"orientation_clockwise={frame.orientation_degrees}"
                    ),
                }
            )
            encoded = base64.b64encode(frame.jpeg).decode("ascii")
            content.append(
                {
                    "type": "input_image",
                    "image_url": f"data:image/jpeg;base64,{encoded}",
                    "detail": self.detail,
                }
            )
        response = self._get_client().responses.parse(
            model=self.model,
            reasoning={"effort": self.reasoning_effort},
            input=[
                {"role": "system", "content": _SCENE_ASSESSMENT_SYSTEM_PROMPT},
                {"role": "user", "content": content},
            ],
            text_format=SceneAssessment,
        )
        parsed = getattr(response, "output_parsed", None)
        if parsed is None:
            raise RuntimeError("GPT scene assessment returned no structured result")
        if isinstance(parsed, SceneAssessment):
            return parsed
        return SceneAssessment.model_validate(parsed)


class ActuatorTools(Protocol):
    mode: str

    def state(self) -> dict[str, object]: ...

    def execute(self, step: CorrectionStep) -> dict[str, object]: ...


def _remote_socket_command(action: str) -> str:
    socket_helper = (
        "def q(c,a=None):\n"
        " s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);"
        "s.settimeout(35);s.connect('/tmp/a1z.sock');"
        "s.sendall((json.dumps({'cmd':c,'args':a or {}})+'\\n').encode());"
        "d=b''\n"
        " while b'\\n' not in d:\n"
        "  x=s.recv(65536)\n"
        "  if not x: break\n"
        "  d+=x\n"
        " s.close();r=json.loads(d.split(b'\\n',1)[0]);"
        "\n if not r.get('ok'): raise RuntimeError(r.get('error','A1Z command failed'))"
        "\n return r['data']\n"
    )
    source = f"import json,socket\n{socket_helper}{action}"
    return (
        "set -e; test -S /tmp/a1z.sock || "
        "{ echo 'A1Z safe daemon socket /tmp/a1z.sock is missing' >&2; exit 20; }; "
        "cd \"$HOME/hardware/robot-arm/a1z-g05-client\"; "
        'env PYTHONPATH=. "$HOME/GALAXEA-A1Z/.venv/bin/python" -c '
        f"{shlex.quote(source)}"
    )


def build_mark_actuator_command(step: CorrectionStep) -> str:
    if step.action is ToolAction.MOVE_TOOL_DELTA:
        assert step.delta_m is not None
        delta = ",".join(f"{value:.9g}" for value in step.delta_m)
        action = (
            f"d=q('move_tool_delta',{{'frame':'base','delta_m':[{delta}],"
            f"'speed':{step.speed:.9g}}});"
            "print(json.dumps(d))"
        )
    else:
        assert step.gripper is not None
        action = (
            f"d=q('gripper',{{'value':{step.gripper:.9g}}});"
            "print(json.dumps(d))"
        )
    return _remote_socket_command(action)


def build_mark_actuator_state_command() -> str:
    return _remote_socket_command(
        "d=q('status');d.update(q('tool_pose'));print(json.dumps(d))"
    )


class SshMarkActuatorTools:
    mode = "ssh-mark"

    def __init__(self, *, host: str = "mark", timeout_s: float = 45.0) -> None:
        self._host = host
        self._timeout_s = timeout_s
        self._lock = threading.Lock()

    def _run(self, command: str) -> dict[str, object]:
        with self._lock:
            try:
                result = subprocess.run(
                    ["ssh", "-o", "BatchMode=yes", self._host, command],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=self._timeout_s,
                )
            except subprocess.TimeoutExpired as exc:
                raise TimeoutError(
                    f"Mark actuator command exceeded {self._timeout_s:.0f}s"
                ) from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise RuntimeError(
                detail or f"Mark actuator command exited with {result.returncode}"
            )
        try:
            data = json.loads(result.stdout.strip().splitlines()[-1])
        except (IndexError, json.JSONDecodeError) as exc:
            raise RuntimeError("Mark returned an invalid actuator response") from exc
        if not isinstance(data, dict):
            raise TypeError("Mark actuator response must be an object")
        return data

    def state(self) -> dict[str, object]:
        return self._run(build_mark_actuator_state_command())

    def execute(self, step: CorrectionStep) -> dict[str, object]:
        return self._run(build_mark_actuator_command(step))


class ShadowActuatorTools:
    mode = "shadow"

    def __init__(self) -> None:
        self.tcp_m = [0.0, 0.0, 0.0]
        self.gripper = 1.0

    def state(self) -> dict[str, object]:
        return {
            "tcp_m": list(self.tcp_m),
            "gripper": self.gripper,
        }

    def execute(self, step: CorrectionStep) -> dict[str, object]:
        if step.action is ToolAction.MOVE_TOOL_DELTA:
            assert step.delta_m is not None
            self.tcp_m = [
                current + delta
                for current, delta in zip(self.tcp_m, step.delta_m, strict=True)
            ]
            return {
                "frame": "base",
                "achieved_delta_m": list(step.delta_m),
                "after_tcp_m": list(self.tcp_m),
            }
        assert step.gripper is not None
        if not math.isfinite(step.gripper):
            raise ValueError("gripper must be finite")
        self.gripper = step.gripper
        return {"gripper": self.gripper}
