import pytest

from hymail_api.imap.utf7 import decode_mailbox, encode_mailbox

# Real folder names taken from a 163 mailbox as they appear on the wire.
LEGACY_ENCODED_NAMES = [
    ("草稿箱", "&g0l6P3ux-"),
    ("已发送", "&XfJT0ZAB-"),
    ("已删除", "&XfJSIJZk-"),
    ("垃圾邮件", "&V4NXPpCuTvY-"),
    ("病毒文件夹", "&dcVr0mWHTvZZOQ-"),
    ("广告邮件", "&Xn9USpCuTvY-"),
    ("订阅邮件", "&i6KWBZCuTvY-"),
    ("其他文件夹/QQ邮件订阅", "&UXZO1mWHTvZZOQ-/QQ&kK5O9ouilgU-"),
]


@pytest.mark.parametrize(("decoded", "encoded"), LEGACY_ENCODED_NAMES)
def test_decode_real_world_names(decoded: str, encoded: str) -> None:
    assert decode_mailbox(encoded) == decoded


@pytest.mark.parametrize(("decoded", "encoded"), LEGACY_ENCODED_NAMES)
def test_encode_real_world_names(decoded: str, encoded: str) -> None:
    assert encode_mailbox(decoded) == encoded


@pytest.mark.parametrize(("decoded", "encoded"), LEGACY_ENCODED_NAMES)
def test_round_trip(decoded: str, encoded: str) -> None:
    assert encode_mailbox(decode_mailbox(encoded)) == encoded
    assert decode_mailbox(encode_mailbox(decoded)) == decoded


def test_ascii_names_pass_through_unchanged() -> None:
    for name in ["INBOX", "Sent Messages", "Drafts", "a/b/c", "~!@#$%^*()"]:
        assert encode_mailbox(name) == name
        assert decode_mailbox(name) == name


def test_ampersand_is_escaped_in_both_directions() -> None:
    assert encode_mailbox("A&B") == "A&-B"
    assert decode_mailbox("A&-B") == "A&B"


def test_mixed_ascii_and_non_ascii_segments() -> None:
    name = "其他文件夹/QQ邮件订阅"
    encoded = "&UXZO1mWHTvZZOQ-/QQ&kK5O9ouilgU-"
    assert encode_mailbox(name) == encoded
    assert decode_mailbox(encoded) == name


def test_non_bmp_characters_survive_the_round_trip() -> None:
    name = "收件箱 📮"
    assert decode_mailbox(encode_mailbox(name)) == name


def test_empty_name() -> None:
    assert encode_mailbox("") == ""
    assert decode_mailbox("") == ""


def test_unterminated_shift_sequence_is_kept_verbatim() -> None:
    # No closing "-", so this is not a valid shifted sequence.
    assert decode_mailbox("&XfJSIJZk") == "&XfJSIJZk"


def test_invalid_shift_payload_is_kept_verbatim() -> None:
    assert decode_mailbox("&not base64!-") == "&not base64!-"


def test_decoding_is_idempotent_on_already_decoded_names() -> None:
    # Guards the migration path: normalizing a name twice must be a no-op.
    for decoded, _ in LEGACY_ENCODED_NAMES:
        assert decode_mailbox(decoded) == decoded
