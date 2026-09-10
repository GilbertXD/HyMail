from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ImapPreset:
    name: str
    host: str
    port: int
    ssl: bool


IMAP_PRESETS: dict[str, ImapPreset] = {
    "163": ImapPreset(name="163", host="imap.163.com", port=993, ssl=True),
    "qq": ImapPreset(name="qq", host="imap.qq.com", port=993, ssl=True),
}


def get_preset(provider: str) -> ImapPreset:
    try:
        return IMAP_PRESETS[provider.lower()]
    except KeyError as exc:
        raise ValueError(f"unknown IMAP provider: {provider}") from exc