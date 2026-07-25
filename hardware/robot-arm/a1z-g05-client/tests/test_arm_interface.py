import pytest

from a1z_g05.arm_interface import A1ZCtlArm


def test_connect_rejects_daemon_with_dead_control_thread() -> None:
    arm = A1ZCtlArm()
    arm._request = lambda *_args, **_kwargs: {
        "control_thread_alive": False,
        "estopped": True,
    }

    with pytest.raises(RuntimeError, match="control thread is not healthy"):
        arm.connect()


def test_connect_accepts_healthy_safe_daemon() -> None:
    arm = A1ZCtlArm()
    arm._request = lambda *_args, **_kwargs: {
        "control_thread_alive": True,
        "estopped": False,
    }

    arm.connect()
