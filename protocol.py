"""DART learning protocol v1: minimal JSON packet format over UDP.

This is an educational wire format, not an interoperable standard.
"""

import json

VERSION = 1
MAX_DATAGRAM_BYTES = 1200  # keep demos below a common internet MTU
MODES = ("unreliable", "partial", "reliable")


class PacketError(ValueError):
    """Invalid or oversized protocol message."""


def encode_packet(packet):
    """Convert a packet dictionary into UTF-8 bytes for socket.sendto()."""
    raw = json.dumps(packet, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(raw) > MAX_DATAGRAM_BYTES:
        raise PacketError(f"Packet is {len(raw)} bytes; max is {MAX_DATAGRAM_BYTES}")
    return raw


def decode_packet(raw):
    """Decode and sanity-check a received UDP datagram."""
    if len(raw) > MAX_DATAGRAM_BYTES:
        raise PacketError("Packet is too large")
    try:
        packet = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PacketError("Packet is not valid UTF-8 JSON") from exc

    if not isinstance(packet, dict) or packet.get("v") != VERSION:
        raise PacketError("Unknown packet version")
    if not isinstance(packet.get("id"), str) or not (1 <= len(packet["id"]) <= 64):
        raise PacketError("Packet must have a valid message ID")
    kind = packet.get("type")
    if kind == "data":
        if packet.get("mode") not in MODES:
            raise PacketError("Unknown reliability mode")
        if not isinstance(packet.get("data"), str):
            raise PacketError("Data payload must be a string")
        deadline = packet.get("deadline_ms")
        if deadline is not None and (type(deadline) is not int or deadline <= 0):
            raise PacketError("Deadline must be a positive integer or null")
        if packet["mode"] == "partial" and deadline is None:
            raise PacketError("Partial messages need a deadline")
    elif kind != "ack":
        raise PacketError("Unknown packet type")
    return packet


def data_packet(message_id, message, mode, deadline_ms=None):
    return {
        "v": VERSION,
        "type": "data",
        "id": message_id,
        "mode": mode,
        "deadline_ms": deadline_ms,
        "data": message,
    }


def ack_packet(message_id):
    return {"v": VERSION, "type": "ack", "id": message_id}
