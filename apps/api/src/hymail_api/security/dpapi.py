def protect_secret(secret: str) -> bytes:
    if not secret:
        raise ValueError("secret must not be empty")
    try:
        import win32crypt
    except ImportError as exc:
        raise RuntimeError("DPAPI requires pywin32") from exc

    return win32crypt.CryptProtectData(
        secret.encode("utf-8"),
        "HyMail",
        None,
        None,
        None,
        0,
    )


def unprotect_secret(blob: bytes) -> str:
    if not blob:
        return ""
    try:
        import win32crypt
    except ImportError as exc:
        raise RuntimeError("DPAPI requires pywin32") from exc

    _description, data = win32crypt.CryptUnprotectData(
        blob,
        None,
        None,
        None,
        0,
    )
    return data.decode("utf-8")