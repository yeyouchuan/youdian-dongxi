from __future__ import annotations

import pytest

from cushion_reminder.simulator import (
    POSTURE_TOPIC,
    RADAR_TOPIC,
    CushionSimulator,
    radar_publish_interval,
)


def test_topics_match_firmware_contract() -> None:
    assert POSTURE_TOPIC == "zuodian/posture"
    assert RADAR_TOPIC == "zuodian/radar"


def test_posture_payload_has_firmware_fields() -> None:
    simulator = CushionSimulator(seed=7, pose="UPRIGHT")

    payload = simulator.posture_payload()

    assert set(payload) == {"s1", "s3", "s4", "s5", "s6", "pose"}
    assert payload["pose"] == "UPRIGHT"
    assert all(0 <= payload[field] <= 4095 for field in ("s1", "s3", "s4", "s5", "s6"))


def test_away_posture_has_only_small_sensor_noise() -> None:
    simulator = CushionSimulator(seed=7, pose="AWAY")

    payload = simulator.posture_payload()

    assert payload["pose"] == "AWAY"
    assert max(payload[field] for field in ("s1", "s3", "s4", "s5", "s6")) <= 8


def test_fresh_radar_frame_advances_sequence_and_exposes_filtered_values() -> None:
    simulator = CushionSimulator(seed=7, pose="UPRIGHT")

    first = simulator.radar_payload(fresh=True)
    second = simulator.radar_payload(fresh=True)

    assert first["seq"] == 1
    assert second["seq"] == 2
    assert set(second) == {"heart", "heart_med", "breath", "breath_med", "dist", "seq"}
    assert 40 <= second["heart_med"] <= 150
    assert 6 <= second["breath_med"] <= 30
    assert 60 <= second["dist"] <= 120


def test_stale_radar_keepalive_reuses_last_frame_and_sequence() -> None:
    simulator = CushionSimulator(seed=7, pose="UPRIGHT")
    fresh = simulator.radar_payload(fresh=True)

    stale = simulator.radar_payload(fresh=False)

    assert stale == fresh
    assert stale is not fresh


def test_stale_radar_before_first_frame_is_rejected() -> None:
    simulator = CushionSimulator(seed=7, pose="UPRIGHT")

    with pytest.raises(RuntimeError, match="before the first fresh frame"):
        simulator.radar_payload(fresh=False)


@pytest.mark.parametrize(
    ("fresh", "expected"),
    [(True, 1.0), (False, 5.0)],
)
def test_radar_publish_interval_matches_firmware(fresh: bool, expected: float) -> None:
    assert radar_publish_interval(fresh) == expected


def test_unknown_pose_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unsupported pose"):
        CushionSimulator(seed=7, pose="SLOUCHING")
