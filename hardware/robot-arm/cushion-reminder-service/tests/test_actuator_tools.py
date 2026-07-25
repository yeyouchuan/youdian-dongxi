import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from cushion_reminder.actuator_tools import (
    CameraGeometry,
    CorrectionPlan,
    CorrectionStep,
    OpenAICorrectionPlanner,
    SceneAssessment,
    ShadowActuatorTools,
    TargetCandidate,
    ToolAction,
    build_mark_actuator_command,
    build_mark_actuator_state_command,
)
from cushion_reminder.vision import (
    REQUIRED_MANIPULATION_VIEWS,
    CameraView,
    ObservationSet,
    VisionFrame,
)


def move_step(delta=(0.01, 0.0, 0.0)) -> CorrectionStep:
    return CorrectionStep(
        action=ToolAction.MOVE_TOOL_DELTA,
        delta_m=delta,
        gripper=None,
        speed=0.08,
        reason="bounded visual correction",
    )


def camera_geometry_payload() -> dict[str, object]:
    def transform(x: float, y: float, z: float) -> list[list[float]]:
        return [
            [1.0, 0.0, 0.0, x],
            [0.0, 1.0, 0.0, y],
            [0.0, 0.0, 1.0, z],
            [0.0, 0.0, 0.0, 1.0],
        ]

    intrinsics = {
        "width": 640,
        "height": 480,
        "fx": 520.0,
        "fy": 520.0,
        "cx": 320.0,
        "cy": 240.0,
    }
    return {
        "calibration_id": "demo-001",
        "coordinate_frame": "a1z_base",
        "views": {
            CameraView.EXTERIOR_RIGHT.value: {
                "parent_frame": "a1z_base",
                "parent_from_camera": transform(0.35, -0.25, 0.45),
                "intrinsics": intrinsics,
                "orientation_degrees": 0,
                "reprojection_error_px": 1.2,
            },
            CameraView.WRIST.value: {
                "parent_frame": "arm_link6",
                "parent_from_camera": transform(0.0, 0.0, 0.08),
                "intrinsics": intrinsics,
                "orientation_degrees": 180,
                "reprojection_error_px": 1.2,
            }
        },
    }


def test_correction_step_rejects_oversized_or_mixed_actuator_arguments() -> None:
    with pytest.raises(ValidationError, match="20 mm"):
        move_step((0.021, 0.0, 0.0))
    with pytest.raises(ValidationError, match="no gripper"):
        CorrectionStep(
            action=ToolAction.MOVE_TOOL_DELTA,
            delta_m=(0.01, 0.0, 0.0),
            gripper=0.5,
            speed=0.08,
            reason="invalid mixed command",
        )


def test_approved_plan_requires_both_views_and_no_person() -> None:
    required = list(REQUIRED_MANIPULATION_VIEWS)
    plan = CorrectionPlan(
        approved=True,
        coordinate_frame="a1z_base",
        selected_target=TargetCandidate.SMALL_CARD,
        target_visible_views=required,
        gripper_visible_views=required,
        person_in_robot_zone=False,
        steps=[move_step()],
        feedback="Both calibrated views agree.",
    )

    assert plan.approved is True
    with pytest.raises(ValidationError, match="both views"):
        CorrectionPlan(
            approved=True,
            coordinate_frame="a1z_base",
            selected_target=TargetCandidate.SMALL_CARD,
            target_visible_views=required[:1],
            gripper_visible_views=required,
            person_in_robot_zone=False,
            steps=[move_step()],
            feedback="One view is missing.",
        )


def test_scene_assessment_selects_one_allowlisted_target_without_actions() -> None:
    assessment = SceneAssessment(
        approved=True,
        selected_target=TargetCandidate.SMALL_CARD,
        target_visible_views=list(REQUIRED_MANIPULATION_VIEWS),
        gripper_visible_views=list(REQUIRED_MANIPULATION_VIEWS),
        person_in_robot_zone=False,
        feedback="The small card and both fingertips are visible.",
    )

    assert assessment.selected_target is TargetCandidate.SMALL_CARD
    assert assessment.target_description == "small flat printed card"
    assert "steps" not in assessment.model_dump()

    wrist_only = SceneAssessment(
        approved=True,
        selected_target=TargetCandidate.CENTER_HAND_MODEL,
        target_visible_views=[CameraView.WRIST],
        gripper_visible_views=list(REQUIRED_MANIPULATION_VIEWS),
        person_in_robot_zone=False,
        feedback="The target and fingertips are clear in wrist; exterior is base-occluded.",
    )
    assert wrist_only.approved is True

    with pytest.raises(ValidationError, match="selected_target"):
        SceneAssessment(
            approved=True,
            selected_target=None,
            target_visible_views=list(REQUIRED_MANIPULATION_VIEWS),
            gripper_visible_views=list(REQUIRED_MANIPULATION_VIEWS),
            person_in_robot_zone=False,
            feedback="Target was not fixed.",
        )

    with pytest.raises(ValidationError, match="shared view"):
        SceneAssessment(
            approved=True,
            selected_target=TargetCandidate.CENTER_HAND_MODEL,
            target_visible_views=[CameraView.WRIST],
            gripper_visible_views=[CameraView.EXTERIOR_RIGHT],
            person_in_robot_zone=False,
            feedback="Target and gripper are not visible together.",
        )


def test_rejected_scene_assessment_discards_model_selected_target() -> None:
    assessment = SceneAssessment(
        approved=False,
        selected_target=TargetCandidate.CENTER_HAND_MODEL,
        target_visible_views=list(REQUIRED_MANIPULATION_VIEWS),
        gripper_visible_views=[CameraView.EXTERIOR_RIGHT],
        person_in_robot_zone=False,
        feedback="The target is not visible in both views.",
    )

    assert assessment.approved is False
    assert assessment.selected_target is None
    assert assessment.feedback == "The target is not visible in both views."


def test_scene_assessment_search_authorization_is_separate_and_human_safe() -> None:
    assessment = SceneAssessment(
        approved=False,
        selected_target=None,
        target_visible_views=[],
        gripper_visible_views=list(REQUIRED_MANIPULATION_VIEWS),
        person_in_robot_zone=False,
        safe_to_search=True,
        feedback="Clear tabletop; a small high-clearance sweep is safe.",
    )

    assert assessment.safe_to_search is True
    with pytest.raises(ValidationError, match="person"):
        SceneAssessment(
            approved=False,
            selected_target=None,
            target_visible_views=[],
            gripper_visible_views=[],
            person_in_robot_zone=True,
            safe_to_search=True,
            feedback="Unsafe search.",
        )


def test_unapproved_plan_cannot_smuggle_actuator_steps() -> None:
    with pytest.raises(ValidationError, match="must not contain"):
        CorrectionPlan(
            approved=False,
            coordinate_frame="a1z_base",
            selected_target=None,
            target_visible_views=[],
            gripper_visible_views=[],
            person_in_robot_zone=False,
            steps=[move_step()],
            feedback="No valid visual evidence.",
        )


def test_mark_command_contains_only_validated_socket_tool_call() -> None:
    command = build_mark_actuator_command(move_step((0.01, -0.005, 0.0)))

    assert "move_tool_delta" in command
    assert "delta_m" in command
    assert "[0.01,-0.005,0]" in command
    assert "/tmp/a1z.sock" in command

    state_command = build_mark_actuator_state_command()
    assert "status" in state_command
    assert "tool_pose" in state_command


def test_shadow_actuator_applies_bounded_move_and_gripper() -> None:
    tools = ShadowActuatorTools()

    moved = tools.execute(move_step((0.01, 0.0, -0.002)))
    gripped = tools.execute(
        CorrectionStep(
            action=ToolAction.SET_GRIPPER,
            delta_m=None,
            gripper=0.2,
            speed=0.08,
            reason="close around aligned object",
        )
    )

    assert moved["after_tcp_m"] == pytest.approx([0.01, 0.0, -0.002])
    assert gripped == {"gripper": 0.2}


def test_camera_geometry_requires_two_rigid_transforms() -> None:
    geometry = CameraGeometry.model_validate(camera_geometry_payload())

    assert geometry.calibration_id == "demo-001"
    assert set(geometry.views) == set(REQUIRED_MANIPULATION_VIEWS)
    assert json.loads(geometry.model_dump_json())["coordinate_frame"] == "a1z_base"

    missing = camera_geometry_payload()
    del missing["views"]["wrist"]
    with pytest.raises(ValidationError, match="exactly two"):
        CameraGeometry.model_validate(missing)


def test_camera_geometry_rejects_wrong_parent_non_rigid_or_bad_reprojection() -> None:
    wrong_parent = camera_geometry_payload()
    wrong_parent["views"]["wrist"]["parent_frame"] = "a1z_base"
    with pytest.raises(ValidationError, match="wrist.*arm_link6"):
        CameraGeometry.model_validate(wrong_parent)

    non_rigid = camera_geometry_payload()
    non_rigid["views"]["exterior_right"]["parent_from_camera"][0][0] = 2.0
    with pytest.raises(ValidationError, match="orthonormal"):
        CameraGeometry.model_validate(non_rigid)

    bad_reprojection = camera_geometry_payload()
    bad_reprojection["views"]["wrist"]["reprojection_error_px"] = 5.1
    with pytest.raises(ValidationError, match="less than or equal to 5"):
        CameraGeometry.model_validate(bad_reprojection)


def test_camera_geometry_resolves_dynamic_wrist_pose_from_current_tool_pose() -> None:
    geometry = CameraGeometry.model_validate(camera_geometry_payload())
    base_from_tool = [
        [1.0, 0.0, 0.0, 0.40],
        [0.0, 1.0, 0.0, 0.10],
        [0.0, 0.0, 1.0, 0.30],
        [0.0, 0.0, 0.0, 1.0],
    ]

    resolved = geometry.resolve({"base_from_tool": base_from_tool})

    assert resolved["views"]["exterior_right"]["base_from_camera"][0][3] == 0.35
    assert resolved["views"]["wrist"]["base_from_camera"][0][3] == 0.40
    assert resolved["views"]["wrist"]["base_from_camera"][2][3] == 0.38
    assert resolved["views"]["wrist"]["intrinsics"]["fx"] == 520.0


def test_camera_geometry_rejects_deprecated_third_view() -> None:
    payload = camera_geometry_payload()
    payload["views"]["exterior_left"] = dict(payload["views"]["exterior_right"])

    with pytest.raises(ValidationError, match="exterior_right.*wrist"):
        CameraGeometry.model_validate(payload)


def test_openai_planner_resolves_wrist_geometry_at_current_tool_pose() -> None:
    class RecordingResponses:
        def __init__(self) -> None:
            self.kwargs = None

        def parse(self, **kwargs):
            self.kwargs = kwargs
            return SimpleNamespace(
                output_parsed={
                    "approved": False,
                    "coordinate_frame": "a1z_base",
                    "selected_target": None,
                    "target_visible_views": [],
                    "gripper_visible_views": [],
                    "person_in_robot_zone": False,
                    "steps": [],
                    "feedback": "test-only rejection",
                }
            )

    responses = RecordingResponses()
    client = SimpleNamespace(responses=responses)
    planner = OpenAICorrectionPlanner(
        camera_geometry=CameraGeometry.model_validate(camera_geometry_payload()),
        client=client,
    )
    now = datetime(2026, 7, 25, tzinfo=timezone.utc)
    observation = ObservationSet(
        captured_at=now,
        frames={
            view: VisionFrame(
                view=view,
                jpeg=b"\xff\xd8test\xff\xd9",
                captured_at=now,
                received_at=now,
                source=view.value,
                orientation_degrees=180 if view is CameraView.WRIST else 0,
            )
            for view in REQUIRED_MANIPULATION_VIEWS
        },
    )
    base_from_tool = [
        [1.0, 0.0, 0.0, 0.40],
        [0.0, 1.0, 0.0, 0.10],
        [0.0, 0.0, 1.0, 0.30],
        [0.0, 0.0, 0.0, 1.0],
    ]

    planner.plan(
        task="grasp one test object",
        selected_target=TargetCandidate.SMALL_CARD,
        observation=observation,
        current_state={"base_from_tool": base_from_tool},
    )

    assert responses.kwargs is not None
    text_items = [
        item["text"]
        for message in responses.kwargs["input"]
        if isinstance(message["content"], list)
        for item in message["content"]
        if item["type"] == "input_text"
    ]
    prompt = "\n".join(text_items)
    assert "small_card" in prompt
    assert '"wrist"' in prompt
    assert "0.38" in prompt
