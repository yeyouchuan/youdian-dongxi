from pathlib import Path

import numpy as np
import yaml

from a1z_g05.mapping import A1ZSo100Mapping, MappingConfig


def test_mark_shadow_config_uses_locked_scaled_direct_mapping() -> None:
    config_path = Path(__file__).resolve().parents[1] / "config.mark-shadow.yaml"
    config = yaml.safe_load(config_path.read_text())
    assert config["mapping"]["mode"] == "direct"
    assert config["mapping"]["arm_joint_indices"] == [0, 1, 2, 4, 5]
    assert config["mapping"]["scales"] == [2, 2, 2, 3, 2]
    assert config["control"]["locked_joint_indices"] == [3]
    assert config["control"]["execute_actions"] is False


def test_mark_gripper_uses_so101_increasing_angle_for_opening() -> None:
    config_path = Path(__file__).resolve().parents[1] / "config.mark-execute.yaml"
    config = yaml.safe_load(config_path.read_text())
    mapping = config["mapping"]

    assert mapping["gripper_deg_closed"] == 0.0
    assert mapping["gripper_deg_open"] == 45.0


def test_mark_execution_allows_spark_cold_inference_without_disabling_outer_timeout() -> None:
    root = Path(__file__).resolve().parents[1]

    for filename in (
        "config.mark-execute.yaml",
        "config.mark-execute-exterior.yaml",
        "config.mark-execute-three-view.yaml",
    ):
        config = yaml.safe_load((root / filename).read_text())
        assert config["server"]["timeout_s"] == 120.0

    two_view = yaml.safe_load((root / "config.mark-execute-two-view.yaml").read_text())
    assert two_view["server"]["timeout_s"] == 300.0


def test_three_view_config_has_no_black_padding() -> None:
    root = Path(__file__).resolve().parents[1]
    config = yaml.safe_load((root / "config.mark-execute-three-view.yaml").read_text())

    assert config["camera"]["server_key"] == "wrist_right"
    assert config["camera"]["zero_pad_keys"] == []
    assert set(config["camera"]["file_images"]) == {"exterior", "wrist_left"}


def test_two_view_config_maps_mark_exterior_and_zero_pads_only_missing_model_slot() -> None:
    root = Path(__file__).resolve().parents[1]
    config = yaml.safe_load((root / "config.mark-execute-two-view.yaml").read_text())

    assert config["camera"]["server_key"] == "wrist_right"
    assert config["camera"]["zero_pad_keys"] == ["wrist_left"]
    assert config["camera"]["file_images"] == {
        "exterior": {
            "path": "/tmp/a1z-vision/exterior-right.jpg",
            "rotate_180": False,
            "max_age_s": 60.0,
        }
    }


def test_mark_base_pose_maps_to_checkpoint_training_mean() -> None:
    config_path = Path(__file__).resolve().parents[1] / "config.mark-execute.yaml"
    config = yaml.safe_load(config_path.read_text())
    mapping_cfg = {k: v for k, v in config["mapping"].items() if k != "mode"}
    mapping = A1ZSo100Mapping(MappingConfig(**mapping_cfg))
    base_pose_deg = np.array(
        [-0.16, 13.50, -23.97, 95.81, 72.90, -30.41],
        dtype=np.float32,
    )

    model_state = mapping.state_to_model(np.deg2rad(base_pose_deg), 1.0)

    # OpenGalaxea/G0.5 SO101 proprio-state mean for the five arm axes.
    expected_arm_mean = np.array(
        [3.1250088, 124.34757, 121.49454, 55.89621, -12.25933],
        dtype=np.float32,
    )
    np.testing.assert_allclose(model_state[:5], expected_arm_mean, atol=1e-3)


def test_three_view_neutral_pose_maps_to_checkpoint_training_mean() -> None:
    config_path = (
        Path(__file__).resolve().parents[1]
        / "config.mark-execute-three-view.yaml"
    )
    config = yaml.safe_load(config_path.read_text())
    mapping_cfg = {k: v for k, v in config["mapping"].items() if k != "mode"}
    mapping = A1ZSo100Mapping(MappingConfig(**mapping_cfg))
    neutral_pose_deg = np.array([0, 60, -60, 0, 0, 0], dtype=np.float32)

    model_state = mapping.state_to_model(np.deg2rad(neutral_pose_deg), 1.0)

    expected_arm_mean = np.array(
        [3.1250088, 124.34757, 121.49454, 55.89621, -12.25933],
        dtype=np.float32,
    )
    np.testing.assert_allclose(model_state[:5], expected_arm_mean, atol=1e-3)


def test_two_view_neutral_pose_maps_to_checkpoint_training_mean() -> None:
    config_path = (
        Path(__file__).resolve().parents[1]
        / "config.mark-execute-two-view.yaml"
    )
    config = yaml.safe_load(config_path.read_text())
    mapping_cfg = {k: v for k, v in config["mapping"].items() if k != "mode"}
    mapping = A1ZSo100Mapping(MappingConfig(**mapping_cfg))
    neutral_pose_deg = np.array([0, 60, -60, 0, 0, 0], dtype=np.float32)

    model_state = mapping.state_to_model(np.deg2rad(neutral_pose_deg), 1.0)

    expected_arm_mean = np.array(
        [3.1250088, 124.34757, 121.49454, 55.89621, -12.25933],
        dtype=np.float32,
    )
    np.testing.assert_allclose(model_state[:5], expected_arm_mean, atol=1e-3)
