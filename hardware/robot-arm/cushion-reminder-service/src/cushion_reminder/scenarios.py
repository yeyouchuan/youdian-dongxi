"""Version-controlled scenarios exposed by the local trigger API."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class CameraProfile:
    id: str
    mark_config_name: str
    required_vid_pid: str
    requires_physical_exterior: bool = False
    requires_diagnostic_opt_in: bool = False


WRIST_SINGLE = CameraProfile(
    id="wrist_single",
    mark_config_name="config.mark-execute.yaml",
    required_vid_pid="2bc5:0557",
)
MOUNTED_AS_EXTERIOR = CameraProfile(
    id="mounted_as_exterior",
    mark_config_name="config.mark-execute-exterior.yaml",
    required_vid_pid="2bc5:0557",
    requires_diagnostic_opt_in=True,
)
TWO_VIEW = CameraProfile(
    id="two_view",
    mark_config_name="config.mark-execute-two-view.yaml",
    required_vid_pid="2bc5:0557",
    requires_physical_exterior=True,
)


@dataclass(frozen=True)
class Scenario:
    id: str
    intent_type: str
    trigger_kind: str
    title: str
    description: str
    prompt: str
    max_steps: int
    camera_profile: CameraProfile

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


SCENARIOS: dict[str, Scenario] = {
    "seated_60m_non_contact_reminder": Scenario(
        id="seated_60m_non_contact_reminder",
        intent_type="non_contact_stand_reminder",
        trigger_kind="continuous_seated_60m",
        title="连续在座 60 分钟：非接触提醒",
        description=("模拟坐垫连续检测到 UPRIGHT 3600 秒；机械臂执行小幅非接触提醒动作。"),
        prompt=(
            "A person has been seated for one hour. Perform a small non-contact "
            "reminder gesture in the cleared robot test zone. Do not approach or "
            "touch the person. Keep the gripper slightly open, then stop."
        ),
        max_steps=64,
        camera_profile=WRIST_SINGLE,
    ),
    "approach_foam_target": Scenario(
        id="approach_foam_target",
        intent_type="approach_fixture",
        trigger_kind="manual_test",
        title="接近固定泡棉靶并停下",
        description=("用当前单相机 exterior 诊断视角识别固定泡棉靶，明显接近并在接触前停止。"),
        prompt=(
            "Locate the fixed foam target in the current exterior view. Move the "
            "gripper clearly toward it, keep the gripper open, and stop "
            "before contact. Do not move toward or touch any person."
        ),
        max_steps=64,
        camera_profile=TWO_VIEW,
    ),
    "locate_person_non_contact_gesture": Scenario(
        id="locate_person_non_contact_gesture",
        intent_type="non_contact_person_gesture",
        trigger_kind="continuous_seated_60m",
        title="识别坐着的人、朝向移动并做非接触手势",
        description=(
            "用 exterior 相机定位坐着的人，朝人的方向明显移动并做指向手势，但始终保持安全距离。"
        ),
        prompt=(
            "Locate the seated person in the current exterior view. Move visibly in "
            "their direction while remaining inside the cleared robot test zone and "
            "maintaining a safe non-contact distance. Make a clear pointing or reminder "
            "gesture toward them. Do not touch the person, then stop."
        ),
        max_steps=64,
        camera_profile=TWO_VIEW,
    ),
    "grasp_lightweight_test_object": Scenario(
        id="grasp_lightweight_test_object",
        intent_type="grasp_test_object",
        trigger_kind="manual_test",
        title="抓取轻质测试物体",
        description=("用 Mark 外部相机与 DaBai 夹爪相机闭环抓取轻质物体并稍微抬起。"),
        prompt=(
            "Locate the lightweight test object in the current exterior view. Move toward "
            "the object, align the open gripper, grasp it, lift it slightly, and "
            "stop. The selected white plastic target must rest directly on the calibrated "
            "white tabletop, never on the laptop, another raised support, or cables. In "
            "the wrist view, place its grasp point laterally between the two fingertips "
            "before any descent. Keep clear of the laptop display, hinge, keyboard, and "
            "cables. Do not move toward or touch any person."
        ),
        # One G0.5 chunk per semantic evaluation. Longer open-loop runs caused
        # target switches before a new exterior observation could be captured.
        max_steps=16,
        camera_profile=TWO_VIEW,
    ),
}


def get_scenario(scenario_id: str) -> Scenario:
    try:
        return SCENARIOS[scenario_id]
    except KeyError as exc:
        raise KeyError(f"Unknown scenario: {scenario_id}") from exc
