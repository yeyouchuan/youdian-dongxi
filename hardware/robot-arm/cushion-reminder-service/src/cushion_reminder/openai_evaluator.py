"""GPT-5.6 post-action evaluation for bounded A1Z manipulation workflows."""

from __future__ import annotations

import base64
import os
from enum import Enum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from .vision import REQUIRED_MANIPULATION_VIEWS, CameraView, ObservationSet


class Verdict(str, Enum):
    SUCCESS = "success"
    RETRY = "retry"
    ABORT = "abort"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class FailureCode(str, Enum):
    WRONG_TARGET = "wrong_target"
    STOPPED_SHORT = "stopped_short"
    OVERSHOT = "overshot"
    MISALIGNED = "misaligned"
    GRIPPER_OPEN = "gripper_open"
    OBJECT_DROPPED = "object_dropped"
    OCCLUDED = "occluded"
    UNSAFE_SCENE = "unsafe_scene"
    NO_PROGRESS = "no_progress"
    NONE = "none"


class NextSubtask(str, Enum):
    REOBSERVE = "reobserve"
    MOVE_CLOSER_WITH_GRIPPER_OPEN = "move_closer_with_gripper_open"
    REALIGN_LEFT = "realign_left"
    REALIGN_RIGHT = "realign_right"
    REALIGN_UP = "realign_up"
    REALIGN_DOWN = "realign_down"
    CLOSE_GRIPPER = "close_gripper"
    LIFT = "lift"
    RETURN_NEUTRAL = "return_neutral"
    STOP = "stop"


class EvaluationVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: Verdict
    position_correct: bool
    target_correct: bool
    calibrated_descent_ready: bool
    grasp_confirmed: bool
    confidence: float = Field(ge=0, le=1)
    failure_code: FailureCode
    evidence: list[str] = Field(min_length=1, max_length=8)
    next_subtask: NextSubtask
    feedback: str = Field(min_length=1, max_length=500)
    requires_new_observation: bool


class ResponsesClient(Protocol):
    class Responses(Protocol):
        def parse(self, **kwargs: object) -> object: ...

    responses: Responses


_SYSTEM_PROMPT = """You are the conservative visual evaluator for a physical Galaxea A1Z
robot arm. Compare BEFORE and AFTER observations from exactly two named views:
exterior_right and wrist. exterior_right is the fixed Mark laptop camera opposite the
gripper. wrist is the DaBai camera mounted on and moving with the gripper; the gripper
tips appear at the bottom of its correctly oriented image.

Decide whether the requested subtask visibly succeeded and whether the correct target is
between both gripper fingertips and lifted clear of the table when a grasp is requested.
Treat false success as the worst error. If a required view is occluded, contradictory, or
does not show enough evidence, return insufficient_evidence. If a person or body part enters
the robot test zone, return abort with unsafe_scene. Do not identify people.

calibrated_descent_ready is independent from depth. Set it true only when the selected
target is visibly resting on the configured horizontal tabletop, its grasp point is
laterally centered between the two wrist-view fingertips, and a straight base-Z descent
would not intersect a laptop, raised support, cable, person, or other obstacle. It may be
true with position_correct=false when the only remaining error is vertical distance.

You provide evaluation only. Never output joint angles, Cartesian coordinates, actuator
values, CAN frames, shell commands, or free-form robot instructions. next_subtask must be
the safest single option from the schema. Camera orientation metadata describes how many
clockwise degrees are needed to display each raw JPEG upright."""


class OpenAIVisionEvaluator:
    """Responses API adapter; it never controls the robot directly."""

    def __init__(
        self,
        *,
        client: ResponsesClient | None = None,
        model: str | None = None,
        detail: str | None = None,
        reasoning_effort: str | None = None,
    ) -> None:
        self._client = client
        self.model = model or os.environ.get("OPENAI_VISION_MODEL", "gpt-5.6")
        self.detail = detail or os.environ.get("OPENAI_VISION_DETAIL", "original")
        self.reasoning_effort = reasoning_effort or os.environ.get(
            "OPENAI_VISION_REASONING_EFFORT", "medium"
        )
        if self.detail not in {"low", "high", "auto", "original"}:
            raise ValueError("OPENAI_VISION_DETAIL must be low, high, auto, or original")
        if self.reasoning_effort not in {
            "none",
            "low",
            "medium",
            "high",
            "xhigh",
            "max",
        }:
            raise ValueError("OPENAI_VISION_REASONING_EFFORT is invalid")

    def _get_client(self) -> ResponsesClient:
        if self._client is not None:
            return self._client
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError(
                "OpenAI evaluator dependency is missing; install the service dependencies"
            ) from exc
        if not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is required for GPT-5.6 visual evaluation")
        self._client = OpenAI()
        return self._client

    @staticmethod
    def _image_item(frame) -> dict[str, str]:
        encoded = base64.b64encode(frame.jpeg).decode("ascii")
        return {
            "type": "input_image",
            "image_url": f"data:image/jpeg;base64,{encoded}",
        }

    def evaluate(
        self,
        *,
        task: str,
        target_description: str,
        subtask: str,
        iteration: int,
        before: ObservationSet,
        after: ObservationSet,
    ) -> EvaluationVerdict:
        content: list[dict[str, str]] = [
            {
                "type": "input_text",
                "text": (
                    f"Task: {task}\n"
                    f"Target: {target_description}\n"
                    f"Current subtask: {subtask}\n"
                    f"Iteration: {iteration}\n"
                    "Evaluate only visible evidence from the paired views below."
                ),
            }
        ]
        for phase, observation in (("BEFORE", before), ("AFTER", after)):
            for view in REQUIRED_MANIPULATION_VIEWS:
                frame = observation.frames[CameraView(view)]
                content.append(
                    {
                        "type": "input_text",
                        "text": (
                            f"{phase} view={view.value} source={frame.source} "
                            f"orientation_clockwise={frame.orientation_degrees}"
                        ),
                    }
                )
                image_item = self._image_item(frame)
                image_item["detail"] = self.detail
                content.append(image_item)

        response = self._get_client().responses.parse(
            model=self.model,
            reasoning={"effort": self.reasoning_effort},
            input=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": content},
            ],
            text_format=EvaluationVerdict,
        )
        parsed = getattr(response, "output_parsed", None)
        if parsed is None:
            raise RuntimeError("GPT-5.6 evaluation returned no structured verdict")
        if isinstance(parsed, EvaluationVerdict):
            return parsed
        return EvaluationVerdict.model_validate(parsed)
