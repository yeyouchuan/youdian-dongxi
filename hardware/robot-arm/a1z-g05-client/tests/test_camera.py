import os
from pathlib import Path

import cv2
import numpy as np
import pytest

from a1z_g05.camera import load_rgb_chw_file, orient_frame


def test_orient_frame_rotates_camera_180_degrees() -> None:
    frame = np.arange(2 * 3 * 3, dtype=np.uint8).reshape(2, 3, 3)

    rotated = orient_frame(frame, rotate_180=True)

    np.testing.assert_array_equal(rotated, frame[::-1, ::-1])


def test_orient_frame_is_unchanged_by_default() -> None:
    frame = np.arange(2 * 3 * 3, dtype=np.uint8).reshape(2, 3, 3)

    np.testing.assert_array_equal(orient_frame(frame, rotate_180=False), frame)


def test_load_rgb_chw_file_resizes_orients_and_checks_freshness(tmp_path: Path) -> None:
    path = tmp_path / "frame.png"
    bgr = np.zeros((2, 3, 3), dtype=np.uint8)
    bgr[0, 0] = [10, 20, 30]
    assert cv2.imwrite(str(path), bgr)
    modified = 1000.0
    os.utime(path, (modified, modified))

    chw = load_rgb_chw_file(
        path,
        target_shape=(3, 2, 3),
        max_age_s=3,
        rotate_180=True,
        now=1001.0,
    )

    assert chw.shape == (3, 2, 3)
    # BGR [10, 20, 30] becomes RGB [30, 20, 10] at bottom-right.
    np.testing.assert_array_equal(chw[:, 1, 2], [30, 20, 10])
    with pytest.raises(RuntimeError, match="stale"):
        load_rgb_chw_file(
            path,
            target_shape=(3, 2, 3),
            max_age_s=3,
            now=1004.1,
        )
