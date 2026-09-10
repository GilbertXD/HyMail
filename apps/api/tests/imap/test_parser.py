from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from hymail_api.imap.parser import parse_message


def test_parse_message_extracts_headers_and_text_parts() -> None:
    message = MIMEMultipart("alternative")
    message["Subject"] = "Hello"
    message["From"] = "Alice <alice@example.com>"
    message["To"] = "Bob <bob@example.com>"
    message["Cc"] = "Carol <carol@example.com>"
    message["Message-ID"] = "<hello@example.com>"
    message["Date"] = "Mon, 01 Jan 2024 00:00:00 +0000"
    message.attach(MIMEText("plain body", "plain", "utf-8"))
    message.attach(MIMEText("<p>html body</p>", "html", "utf-8"))

    parsed = parse_message(message.as_bytes())

    assert parsed.subject == "Hello"
    assert parsed.from_name == "Alice"
    assert parsed.from_addr == "alice@example.com"
    assert parsed.to == ["Bob <bob@example.com>"]
    assert parsed.cc == ["Carol <carol@example.com>"]
    assert parsed.message_id == "<hello@example.com>"
    assert parsed.date is not None
    assert parsed.body_text == "plain body"
    assert parsed.body_html == "<p>html body</p>"


def test_parse_message_without_body_returns_none_body() -> None:
    parsed = parse_message(b"Subject: No body\r\n\r\n")
    assert parsed.subject == "No body"
    assert parsed.body_text is None
    assert parsed.body_html is None