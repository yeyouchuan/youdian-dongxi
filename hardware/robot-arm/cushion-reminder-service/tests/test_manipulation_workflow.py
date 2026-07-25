from __future__ import annotations

from datetime import datetime, timezone

import pytest

from cushion_reminder.actuator_tools import (
    CorrectionPlan,
    CorrectionStep,
    SceneAssessment,
    TargetCandidate,
    ToolAction,
)
from cushion_reminder.execution import ExecutionResult
from cushion_reminder.manipulation_workflow import (
    CORRECTIVE_STEPS,
    ManipulationWorkflow,
)
from cushion_reminder.openai_evaluator import EvaluationVerdict
from cushion_reminder.scenarios import SCENARIOS
from cushion_reminder.vision import REQUIRED_MANIPULATION_VIEWS, ObservationSet

EMPTY_OBSERVATION = ObservationSet(
    captured_at=datetime(2026, 7, 25, tzinfo=timezone.utc),
    frames={},
)


class RecordingExecutor:
    mode = "ssh-mark"

    def __init__(self) -> None:
        self.scenarios = []

    def execute(self, scenario, log) -> ExecutionResult:
        self.scenarios.append(scenario)
        return ExecutionResult(steps_requested=scenario.max_steps, mode=self.mode)


class FakeObserver:
    def __init__(self) -> None:
        self.phases = []

    def start(self, log) -> None:
        self.phases.append("start")

    def observe(self, *, phase, log) -> ObservationSet:
        self.phases.append(phase)
        return EMPTY_OBSERVATION

    def stop(self, log) -> None:
        self.phases.append("stop")


def verdict(
    kind: str,
    next_subtask: str,
    failure_code: str = "none",
    *,
    calibrated_descent_ready: bool = False,
) -> EvaluationVerdict:
    return EvaluationVerdict.model_validate(
        {
            "verdict": kind,
            "position_correct": kind == "success",
            "target_correct": True,
            "calibrated_descent_ready": calibrated_descent_ready,
            "grasp_confirmed": kind == "success",
            "confidence": 0.9,
            "failure_code": failure_code,
            "evidence": ["test evidence"],
            "next_subtask": next_subtask,
            "feedback": "untrusted free-form feedback must not enter the next prompt",
            "requires_new_observation": False,
        }
    )


class FakeEvaluator:
    def __init__(self, verdicts) -> None:
        self.verdicts = list(verdicts)
        self.calls = []

    def evaluate(self, **kwargs) -> EvaluationVerdict:
        result = self.verdicts[len(self.calls)]
        self.calls.append(kwargs)
        return result


class FakePlanner:
    def __init__(self, *, assessments, plans=()) -> None:
        self.assessments = list(assessments)
        self.plans = list(plans)
        self.assessment_calls = []
        self.plan_calls = []

    def assess_scene(self, **kwargs) -> SceneAssessment:
        result = self.assessments[len(self.assessment_calls)]
        self.assessment_calls.append(kwargs)
        return result

    def plan(self, **kwargs) -> CorrectionPlan:
        result = self.plans[len(self.plan_calls)]
        self.plan_calls.append(kwargs)
        return result


class FakeActuators:
    mode = "ssh-mark"

    def __init__(self) -> None:
        self.steps = []
        self.state_calls = 0

    def state(self) -> dict[str, object]:
        self.state_calls += 1
        return {
            "joints_degrees": [0, 60, -60, 10, 0, 0],
            "gripper": 1.0,
        }

    def execute(self, step: CorrectionStep) -> dict[str, object]:
        self.steps.append(step)
        return {"accepted": True}


def correction_plan(
    *,
    approved: bool,
    action: ToolAction = ToolAction.MOVE_TOOL_DELTA,
    target: TargetCandidate = TargetCandidate.SMALL_CARD,
) -> CorrectionPlan:
    step = (
        CorrectionStep(
            action=ToolAction.MOVE_TOOL_DELTA,
            delta_m=(0.01, 0.0, 0.0),
            gripper=None,
            speed=0.08,
            reason="move toward the visually aligned target",
        )
        if action is ToolAction.MOVE_TOOL_DELTA
        else CorrectionStep(
            action=ToolAction.SET_GRIPPER,
            delta_m=None,
            gripper=0.25,
            speed=0.08,
            reason="close around the aligned lightweight target",
        )
    )
    views = list(REQUIRED_MANIPULATION_VIEWS) if approved else []
    return CorrectionPlan(
        approved=approved,
        coordinate_frame="a1z_base",
        selected_target=target if approved else None,
        target_visible_views=views,
        gripper_visible_views=views,
        person_in_robot_zone=False,
        steps=[step] if approved else [],
        feedback="all views agree" if approved else "wrist view misses the target",
    )


def scene_assessment(
    *,
    approved: bool,
    target: TargetCandidate | None = TargetCandidate.SMALL_CARD,
    person_in_robot_zone: bool = False,
    safe_to_search: bool = False,
) -> SceneAssessment:
    views = list(REQUIRED_MANIPULATION_VIEWS) if approved else []
    return SceneAssessment(
        approved=approved,
        selected_target=target if approved else None,
        target_visible_views=views,
        gripper_visible_views=views,
        person_in_robot_zone=person_in_robot_zone,
        safe_to_search=safe_to_search,
        feedback="all views agree" if approved else "wrist view misses the target",
    )


def test_retry_uses_allowlisted_prompt_and_stops_after_visual_success() -> None:
    executor = RecordingExecutor()
    observer = FakeObserver()
    evaluator = FakeEvaluator(
        [
            verdict("retry", "move_closer_with_gripper_open", "stopped_short"),
            verdict("success", "stop"),
        ]
    )
    events = []
    workflow = ManipulationWorkflow(
        executor=executor,
        observer=observer,
        evaluator=evaluator,
    )

    result = workflow.run(
        SCENARIOS["grasp_lightweight_test_object"],
        lambda level, message, data: events.append((level, message, data)),
    )

    assert len(executor.scenarios) == 2
    assert executor.scenarios[1].max_steps == CORRECTIVE_STEPS
    assert "Move slightly closer" in executor.scenarios[1].prompt
    assert "untrusted free-form feedback" not in executor.scenarios[1].prompt
    assert result.steps_requested == (
        SCENARIOS["grasp_lightweight_test_object"].max_steps + CORRECTIVE_STEPS
    )
    assert observer.phases == ["start", "before", "after", "after", "stop"]
    assert any("visual verdict: success" in message for _, message, _ in events)


def test_scene_assessor_can_select_target_without_enabling_actuator_tools() -> None:
    executor = RecordingExecutor()
    observer = FakeObserver()
    evaluator = FakeEvaluator([verdict("success", "stop")])
    assessor = FakePlanner(assessments=[scene_assessment(approved=True)])
    workflow = ManipulationWorkflow(
        executor=executor,
        observer=observer,
        evaluator=evaluator,
        scene_assessor=assessor,
    )

    workflow.run(
        SCENARIOS["grasp_lightweight_test_object"],
        lambda *_args: None,
    )

    assert len(assessor.assessment_calls) == 1
    assert assessor.plan_calls == []
    assert "small flat printed card" in executor.scenarios[0].prompt


def test_missing_target_runs_bounded_search_then_locks_found_target() -> None:
    executor = RecordingExecutor()
    observer = FakeObserver()
    evaluator = FakeEvaluator([verdict("success", "stop")])
    assessor = FakePlanner(
        assessments=[
            scene_assessment(
                approved=False,
                target=None,
                safe_to_search=True,
            ),
            scene_assessment(approved=True),
        ]
    )
    workflow = ManipulationWorkflow(
        executor=executor,
        observer=observer,
        evaluator=evaluator,
        scene_assessor=assessor,
    )

    workflow.run(
        SCENARIOS["grasp_lightweight_test_object"],
        lambda *_args: None,
    )

    assert len(executor.scenarios) == 2
    assert "Search the reachable tabletop" in executor.scenarios[0].prompt
    assert "Keep the gripper fully open" in executor.scenarios[0].prompt
    assert "small flat printed card" in executor.scenarios[1].prompt
    assert observer.phases == ["start", "before", "search_after_1", "after", "stop"]


def test_unsafe_scene_aborts_without_another_action() -> None:
    executor = RecordingExecutor()
    observer = FakeObserver()
    evaluator = FakeEvaluator([verdict("abort", "stop", "unsafe_scene")])
    workflow = ManipulationWorkflow(
        executor=executor,
        observer=observer,
        evaluator=evaluator,
    )

    try:
        workflow.run(
            SCENARIOS["grasp_lightweight_test_object"],
            lambda *_args: None,
        )
    except RuntimeError as exc:
        assert "unsafe_scene" in str(exc)
    else:
        raise AssertionError("unsafe evaluator verdict must abort")

    assert len(executor.scenarios) == 1
    assert observer.phases[-1] == "stop"


def test_semantic_scene_gate_blocks_g05_before_any_physical_action() -> None:
    executor = RecordingExecutor()
    observer = FakeObserver()
    evaluator = FakeEvaluator([])
    planner = FakePlanner(
        assessments=[
            scene_assessment(
                approved=False,
                person_in_robot_zone=True,
            )
        ]
    )
    actuators = FakeActuators()
    workflow = ManipulationWorkflow(
        executor=executor,
        observer=observer,
        evaluator=evaluator,
        planner=planner,
        actuators=actuators,
    )

    with pytest.raises(RuntimeError, match="wrist view misses the target"):
        workflow.run(
            SCENARIOS["grasp_lightweight_test_object"],
            lambda *_args: None,
        )

    assert executor.scenarios == []
    assert actuators.steps == []
    assert actuators.state_calls == 0
    assert observer.phases == ["start", "before", "stop"]


def test_failed_g05_uses_one_gpt_tool_step_then_reobserves_before_success() -> None:
    executor = RecordingExecutor()
    observer = FakeObserver()
    evaluator = FakeEvaluator(
        [
            verdict("retry", "close_gripper", "gripper_open"),
            verdict("success", "stop"),
        ]
    )
    planner = FakePlanner(
        assessments=[scene_assessment(approved=True)],
        plans=[
            correction_plan(approved=True, action=ToolAction.SET_GRIPPER),
        ],
    )
    actuators = FakeActuators()
    events = []
    workflow = ManipulationWorkflow(
        executor=executor,
        observer=observer,
        evaluator=evaluator,
        planner=planner,
        actuators=actuators,
    )

    result = workflow.run(
        SCENARIOS["grasp_lightweight_test_object"],
        lambda level, message, data: events.append((level, message, data)),
    )

    assert len(executor.scenarios) == 1
    assert "small flat printed card" in executor.scenarios[0].prompt
    assert evaluator.calls[0]["target_description"] == "small flat printed card"
    assert len(actuators.steps) == 1
    assert actuators.steps[0].action is ToolAction.SET_GRIPPER
    assert observer.phases == [
        "start",
        "before",
        "after",
        "actuator_after_1",
        "stop",
    ]
    assert len(planner.assessment_calls) == 1
    assert len(planner.plan_calls) == 1
    assert actuators.state_calls == 1
    assert result.steps_requested == (
        SCENARIOS["grasp_lightweight_test_object"].max_steps + 1
    )
    assert any("GPT actuator step 1" in message for _, message, _ in events)


def test_gpt_actuator_cannot_switch_away_from_scene_selected_target() -> None:
    executor = RecordingExecutor()
    observer = FakeObserver()
    evaluator = FakeEvaluator(
        [verdict("retry", "move_closer_with_gripper_open", "stopped_short")]
    )
    planner = FakePlanner(
        assessments=[scene_assessment(approved=True)],
        plans=[
            correction_plan(
                approved=True,
                target=TargetCandidate.LEFT_HAND_MODEL,
            )
        ],
    )
    actuators = FakeActuators()
    workflow = ManipulationWorkflow(
        executor=executor,
        observer=observer,
        evaluator=evaluator,
        planner=planner,
        actuators=actuators,
    )

    with pytest.raises(RuntimeError, match="switch targets"):
        workflow.run(
            SCENARIOS["grasp_lightweight_test_object"],
            lambda *_args: None,
        )

    assert actuators.steps == []
