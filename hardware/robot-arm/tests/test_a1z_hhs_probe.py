from scripts.a1z_hhs_probe import supports_mode, usb_id


def test_usb_id_uses_four_digit_lowercase_hex() -> None:
    assert usb_id(0xA8FA, 0x8598) == "a8fa:8598"


def test_supports_mode_requires_the_requested_bit() -> None:
    assert supports_mode(0b1010, 0b0010)
    assert not supports_mode(0b1000, 0b0010)
