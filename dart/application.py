"""Tiny application format for sending text and files over DART."""

from pathlib import Path


TEXT_MESSAGE = 1
FILE_MESSAGE = 2


def encode_text(text):
    return bytes([TEXT_MESSAGE]) + text.encode("utf-8")


def encode_file(filename, data):
    """Add a filename before raw file bytes."""
    if not isinstance(data, bytes):
        raise ValueError("File data must be bytes")
    filename = Path(filename).name
    name_bytes = filename.encode("utf-8")
    if not name_bytes or len(name_bytes) > 65535:
        raise ValueError("Filename must be between 1 and 65535 bytes")
    return bytes([FILE_MESSAGE]) + len(name_bytes).to_bytes(2, "big") + name_bytes + data


def decode_message(data):
    """Return (kind, filename, content) from a complete DART message."""
    if not data:
        raise ValueError("Application message is empty")

    if data[0] == TEXT_MESSAGE:
        return "text", None, data[1:].decode("utf-8")

    if data[0] == FILE_MESSAGE:
        if len(data) < 3:
            raise ValueError("File message is missing its filename length")
        name_length = int.from_bytes(data[1:3], "big")
        name_end = 3 + name_length
        if name_length == 0 or len(data) < name_end:
            raise ValueError("File message has an invalid filename")

        filename = data[3:name_end].decode("utf-8")
        if (
            filename in (".", "..")
            or "/" in filename
            or "\\" in filename
            or Path(filename).name != filename
        ):
            raise ValueError("File message contains an unsafe filename")
        return "file", filename, data[name_end:]

    raise ValueError("Unknown application message type")
