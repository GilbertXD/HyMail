import pytest

from hymail_api.imap.presets import get_preset


def test_163_preset() -> None:
    preset = get_preset("163")
    assert preset.host == "imap.163.com"
    assert preset.port == 993
    assert preset.ssl is True


def test_qq_preset() -> None:
    preset = get_preset("qq")
    assert preset.host == "imap.qq.com"
    assert preset.port == 993
    assert preset.ssl is True


def test_unknown_preset_raises() -> None:
    with pytest.raises(ValueError):
        get_preset("unknown")