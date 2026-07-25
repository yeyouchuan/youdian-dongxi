"""Bounded G0.5 action → two-view GPT evaluation → safe retry workflow."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Protocol

from .actuator_tools import (
    ActuatorTools,
    CorrectionPlan,
    OpenAICorrectionPlanner,
    SceneAssessment,
    TargetCandidate,
)
from .execution import ExecutionResult, LogCallback, RobotExecutor
from .openai_evaluator import (
    EvaluationVerdict,
    NextSubtask,
    OpenAIVisionEvaluator,
    Verdict,
)
from .scenarios import Scenario
from .vision import ObservationSet

MAX_TOTAL_ACTION_STEPS = 96
MAX_CORRECTIVE_ITERATIONS = 5
MAX_EVALUATIONS = 7
CORRECTIVE_STEPS = 16
MAX_ACTUATOR_CORRECTIONS = 6
MAX_SEARCH_ITERATIONS = 3
_SEARCH_SWEEP_TEXT = (
    "Pan the high-clearance wrist view left across the reachable tabletop.",
    "Pan right across the centre and opposite side of the reachable tabletop.",
    "Tilt the high-clearance wrist view slightly forward/down to cover the near tabletop.",
)


class ObservationAdapter(Protocol):
    def start(self, log: LogCallback) -> None: ...

    def observe(self, *, phase: str, log: LogCallback) -> ObservationSet: ...

    def stop(self, log: LogCallback) -> None: ...


class ActionEvaluator(Protocol):
    def evaluate(
        self,
        *,
        task: str,
        target_description: str,
        subtask: str,
        iteration: int,
        before: ObservationSet,
        after: ObservationSet,
    ) -> EvaluationVerdict: ...


class SceneAssessor(Protocol):
    def assess_scene(
        self,
        *,
        task: str,
        observation: ObservationSet,
    ) -> SceneAssessment: ...


class CorrectionPlanner(SceneAssessor, Protocol):
    def plan(
        self,
        *,
        task: str,
        selected_target: TargetCandidate,
        observation: ObservationSet,
        current_state: dict[str, object],
    ) -> CorrectionPlan: ...


_SAFE_SUBTASK_TEXT = {
    NextSubtask.MOVE_CLOSER_WITH_GRIPPER_OPEN: (
        "Move slightly closer to the same test object with the gripper open, then stop."
    ),
    NextSubtask.REALIGN_LEFT: (
        "Realign slightly left relative to the same test object with the gripper open, "
        "then stop."
    ),
    NextSubtask.REALIGN_RIGHT: (
        "Realign slightly right relative to the same test object with the gripper open, "
        "then stop."
    ),
    NextSubtask.REALIGN_UP: (
        "Realign slightly upward relative to the same test object with the gripper open, "
        "then stop."
    ),
    NextSubtask.REALIGN_DOWN: (
        "Realign slightly downward relative to the same test object with the gripper open, "
        "then stop."
    ),
    NextSubtask.CLOSE_GRIPPER: (
        "Keep the current alignment and close the gripper around the same test object, "
        "then stop."
    ),
    NextSubtask.LIFT: (
        "Keep holding the same test object, lift it slightly clear of the table, then stop."
    ),
}


def corrective_scenario(original: Scenario, next_subtask: NextSubtask) -> Scenario:
    try:
        safe_subtask = _SAFE_SUBTASK_TEXT[next_subtask]
    except KeyError as exc:
        raise RuntimeError(
            f"Evaluator requested non-motion or unsupported subtask: {next_subtask.value}"
        ) from exc
    prompt = (
        "Goal: grasp and slightly lift the same lightweight test object selected in the "
        f"previous observation. Next safe subtask: {safe_subtask} "
        "Stay inside the cleared robot test zone. Do not move toward or touch any person."
    )
    return replace(
        original,
        prompt=prompt,
        max_steps=CORRECTIVE_STEPS,
    )


def search_scenario(original: Scenario, search_iteration: int) -> Scenario:
    sweep = _SEARCH_SWEEP_TEXT[search_iteration - 1]
    return replace(
        original,
        prompt=(
            "Search the reachable tabletop for one white plastic test model. Keep the "
            "gripper fully open. Move the wrist camera through one small, deliberate "
            f"search sweep ({search_iteration}/{MAX_SEARCH_ITERATIONS}): {sweep} Then "
            "stop for "
            "a new two-view observation. Do not close the gripper, descend toward the "
            "table, or move toward any person."
        ),
        max_steps=CORRECTIVE_STEPS,
    )


class ManipulationWorkflow:
    """Deep module that owns observation pairing, evaluation, and retry budgets."""

    def __init__(
        self,
        *,
        executor: RobotExecutor,
        observer: ObservationAdapter,
        evaluator: ActionEvaluator | OpenAIVisionEvaluator,
        scene_assessor: SceneAssessor | OpenAICorrectionPlanner | None = None,
        planner: CorrectionPlanner | OpenAICorrectionPlanner | None = None,
        actuators: ActuatorTools | None = None,
    ) -> None:
        if (planner is None) != (actuators is None):
            raise ValueError("planner and actuators must be configured together")
        self._executor = executor
        self._observer = observer
        self._evaluator = evaluator
        self._scene_assessor = scene_assessor or planner
        self._planner = planner
        self._actuators = actuators

    def run(self, scenario: Scenario, log: LogCallback) -> ExecutionResult:
        if scenario.intent_type != "grasp_test_object":
            raise ValueError("ManipulationWorkflow only accepts grasp_test_object intents")
        total_steps = 0
        corrective_iterations = 0
        evaluations = 0
        reobserve_used = False
        iteration = 0
        current = scenario
        selected_target: TargetCandidate | None = None
        target_description = "the same lightweight test object selected at iteration 0"
        self._observer.start(log)
        try:
            before = self._observer.observe(phase="before", log=log)
            if self._scene_assessor is not None:
                assessment = self._scene_assessor.assess_scene(
                    task=scenario.prompt,
                    observation=before,
                )
                self._log_scene_assessment(log, assessment, phase="initial")
                search_iteration = 0
                while not assessment.approved:
                    if assessment.person_in_robot_zone:
                        raise RuntimeError(
                            "Semantic scene gate rejected manipulation: "
                            f"{assessment.feedback}"
                        )
                    if not assessment.safe_to_search:
                        raise RuntimeError(
                            "Semantic scene gate did not authorize a search sweep: "
                            f"{assessment.feedback}"
                        )
                    if search_iteration >= MAX_SEARCH_ITERATIONS:
                        raise RuntimeError(
                            "Automatic tabletop search exhausted without finding "
                            "an allowlisted target"
                        )
                    search_iteration += 1
                    search = search_scenario(scenario, search_iteration)
                    if total_steps + search.max_steps > MAX_TOTAL_ACTION_STEPS:
                        raise RuntimeError("Manipulation action-step budget exhausted")
                    log(
                        "search",
                        f"Automatic tabletop search sweep {search_iteration}",
                        {
                            "iteration": search_iteration,
                            "max_iterations": MAX_SEARCH_ITERATIONS,
                            "max_steps": search.max_steps,
                        },
                    )
                    self._executor.execute(search, log)
                    total_steps += search.max_steps
                    before = self._observer.observe(
                        phase=f"search_after_{search_iteration}",
                        log=log,
                    )
                    assessment = self._scene_assessor.assess_scene(
                        task=scenario.prompt,
                        observation=before,
                    )
                    self._log_scene_assessment(
                        log,
                        assessment,
                        phase=f"search-{search_iteration}",
                    )
                selected_target = assessment.selected_target
                assert selected_target is not None
                target_description = assessment.target_description
                current = replace(
                    scenario,
                    prompt=(
                        f"{scenario.prompt} Selected target: {target_description}. "
                        "Keep this exact target identity for every action; do not switch "
                        "to another object."
                    ),
                )
            while True:
                requested = current.max_steps
                if total_steps + requested > MAX_TOTAL_ACTION_STEPS:
                    raise RuntimeError("Manipulation action-step budget exhausted")
                log(
                    "workflow",
                    f"Manipulation iteration {iteration}: dispatching G0.5 action",
                    {
                        "iteration": iteration,
                        "max_steps": requested,
                        "total_steps_before": total_steps,
                    },
                )
                self._executor.execute(current, log)
                total_steps += requested
                after = self._observer.observe(phase="after", log=log)
                verdict = self._evaluate(
                    scenario=scenario,
                    current=current,
                    target_description=target_description,
                    iteration=iteration,
                    before=before,
                    after=after,
                )
                evaluations += 1
                self._log_verdict(log, iteration, verdict)

                if verdict.verdict is Verdict.SUCCESS:
                    return ExecutionResult(
                        steps_requested=total_steps,
                        mode=self._executor.mode,
                    )
                if verdict.verdict is Verdict.ABORT:
                    raise RuntimeError(
                        f"Visual evaluator aborted manipulation: {verdict.failure_code.value}"
                    )
                if verdict.verdict is Verdict.INSUFFICIENT_EVIDENCE:
                    if reobserve_used or evaluations >= MAX_EVALUATIONS:
                        raise RuntimeError(
                            "Visual evaluator still lacks evidence after one re-observation"
                        )
                    reobserve_used = True
                    after = self._observer.observe(phase="reobserve", log=log)
                    verdict = self._evaluate(
                        scenario=scenario,
                        current=current,
                        target_description=target_description,
                        iteration=iteration,
                        before=before,
                        after=after,
                    )
                    evaluations += 1
                    self._log_verdict(log, iteration, verdict)
                    if verdict.verdict is Verdict.SUCCESS:
                        return ExecutionResult(
                            steps_requested=total_steps,
                            mode=self._executor.mode,
                        )
                    if verdict.verdict is not Verdict.RETRY:
                        raise RuntimeError(
                            "Visual evidence remained insufficient or unsafe after re-observation"
                        )

                if self._planner is not None:
                    assert selected_target is not None
                    return self._run_actuator_corrections(
                        scenario=scenario,
                        selected_target=selected_target,
                        target_description=target_description,
                        observation=after,
                        total_g05_steps=total_steps,
                        iteration=iteration,
                        log=log,
                    )
                if corrective_iterations >= MAX_CORRECTIVE_ITERATIONS:
                    raise RuntimeError("Manipulation corrective-iteration budget exhausted")
                if evaluations >= MAX_EVALUATIONS:
                    raise RuntimeError("Manipulation evaluation budget exhausted")
                current = corrective_scenario(scenario, verdict.next_subtask)
                corrective_iterations += 1
                iteration += 1
                before = after
        finally:
            self._observer.stop(log)

    def _evaluate(
        self,
        *,
        scenario: Scenario,
        current: Scenario,
        target_description: str,
        iteration: int,
        before: ObservationSet,
        after: ObservationSet,
    ) -> EvaluationVerdict:
        return self._evaluator.evaluate(
            task=scenario.prompt,
            target_description=target_description,
            subtask=current.prompt,
            iteration=iteration,
            before=before,
            after=after,
        )

    def _plan_correction(
        self,
        *,
        scenario: Scenario,
        selected_target: TargetCandidate,
        observation: ObservationSet,
        log: LogCallback,
        phase: str,
    ) -> CorrectionPlan:
        assert self._planner is not None
        assert self._actuators is not None
        plan = self._planner.plan(
            task=scenario.prompt,
            selected_target=selected_target,
            observation=observation,
            current_state=self._actuators.state(),
        )
        log(
            "planning",
            f"GPT-5.6 correction plan: {'approved' if plan.approved else 'rejected'}",
            {
                "phase": phase,
                **plan.model_dump(mode="json"),
            },
        )
        return plan

    def _run_actuator_corrections(
        self,
        *,
        scenario: Scenario,
        selected_target: TargetCandidate,
        target_description: str,
        observation: ObservationSet,
        total_g05_steps: int,
        iteration: int,
        log: LogCallback,
    ) -> ExecutionResult:
        assert self._actuators is not None
        current = observation
        for actuator_index in range(1, MAX_ACTUATOR_CORRECTIONS + 1):
            plan = self._plan_correction(
                scenario=scenario,
                selected_target=selected_target,
                observation=current,
                log=log,
                phase=f"actuator-before-{actuator_index}",
            )
            if not plan.approved:
                raise RuntimeError(
                    "GPT actuator correction rejected by semantic scene gate: "
                    f"{plan.feedback}"
                )
            if plan.selected_target is not selected_target:
                raise RuntimeError("GPT actuator correction attempted to switch targets")
            # Never execute a stale multi-step plan. Re-observe and re-plan after the
            # first bounded physical action, even when GPT proposed more.
            step = plan.steps[0]
            result = self._actuators.execute(step)
            log(
                "actuator",
                f"GPT actuator step {actuator_index}: {step.action.value}",
                {
                    "step": step.model_dump(mode="json"),
                    "result": result,
                    "discarded_stale_steps": max(0, len(plan.steps) - 1),
                },
            )
            after = self._observer.observe(
                phase=f"actuator_after_{actuator_index}",
                log=log,
            )
            verdict = self._evaluator.evaluate(
                task=scenario.prompt,
                target_description=target_description,
                subtask=step.reason,
                iteration=iteration + actuator_index,
                before=current,
                after=after,
            )
            self._log_verdict(log, iteration + actuator_index, verdict)
            if verdict.verdict is Verdict.SUCCESS:
                return ExecutionResult(
                    steps_requested=total_g05_steps + actuator_index,
                    mode=self._executor.mode,
                )
            if verdict.verdict is Verdict.ABORT:
                raise RuntimeError(
                    "Visual evaluator aborted actuator correction: "
                    f"{verdict.failure_code.value}"
                )
            if verdict.verdict is Verdict.INSUFFICIENT_EVIDENCE:
                raise RuntimeError(
                    "Actuator correction lacks two-view visual evidence"
                )
            current = after
        raise RuntimeError("GPT actuator-correction budget exhausted")

    @staticmethod
    def _log_scene_assessment(
        log: Callable[[str, str, dict[str, object] | None], None],
        assessment: SceneAssessment,
        *,
        phase: str,
    ) -> None:
        log(
            "planning",
            (
                "GPT-5.6 scene assessment: "
                f"{'approved' if assessment.approved else 'rejected'}"
            ),
            {
                "phase": phase,
                **assessment.model_dump(mode="json"),
            },
        )

    @staticmethod
    def _log_verdict(
        log: Callable[[str, str, dict[str, object] | None], None],
        iteration: int,
        verdict: EvaluationVerdict,
    ) -> None:
        log(
            "evaluation",
            f"GPT-5.6 visual verdict: {verdict.verdict.value}",
            {
                "iteration": iteration,
                **verdict.model_dump(mode="json"),
            },
        )
