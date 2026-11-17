"""Pre-shared-key authentication and DATA packet encryption."""

from dataclasses import replace
import hashlib
import hmac
import struct

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

from .packet import VERSION


ENCRYPTED_FLAG = 1
AEAD_TAG_BYTES = 16


class SecurityError(ValueError):
    """A key or authenticated packet is invalid."""


def parse_key(key_hex):
    """Parse a 32-byte key written as 64 hexadecimal characters."""
    try:
        key = bytes.fromhex(key_hex)
    except (TypeError, ValueError) as error:
        raise SecurityError("Key must be 64 hexadecimal characters") from error
    if len(key) != 32:
        raise SecurityError("Key must be 64 hexadecimal characters")
    return key


def derive_session_key(pre_shared_key, connection_id, client_nonce, server_nonce):
    message = (
        b"DART-SESSION"
        + connection_id.to_bytes(8, "big")
        + client_nonce
        + server_nonce
    )
    return hmac.new(pre_shared_key, message, hashlib.sha256).digest()


def sign_hello(packet, pre_shared_key):
    tag = _hmac(pre_shared_key, b"HELLO" + _handshake_data(packet))
    return replace(packet, auth_tag=tag)


def verify_hello(packet, pre_shared_key):
    expected = _hmac(pre_shared_key, b"HELLO" + _handshake_data(packet))
    if not hmac.compare_digest(packet.auth_tag, expected):
        raise SecurityError("HELLO authentication failed")


def sign_hello_ack(packet, pre_shared_key, client_nonce):
    data = b"HELLO-ACK" + client_nonce + _handshake_data(packet)
    return replace(packet, auth_tag=_hmac(pre_shared_key, data))


def verify_hello_ack(packet, pre_shared_key, client_nonce):
    data = b"HELLO-ACK" + client_nonce + _handshake_data(packet)
    expected = _hmac(pre_shared_key, data)
    if not hmac.compare_digest(packet.auth_tag, expected):
        raise SecurityError("HELLO_ACK authentication failed")


def encrypt_data(packet, session_key):
    encrypted_packet = replace(packet, flags=packet.flags | ENCRYPTED_FLAG)
    cipher = ChaCha20Poly1305(session_key)
    payload = cipher.encrypt(
        _packet_nonce(session_key, packet.connection_id, packet.packet_number),
        packet.payload,
        _data_aad(encrypted_packet),
    )
    return replace(encrypted_packet, payload=payload)


def decrypt_data(packet, session_key):
    if not packet.flags & ENCRYPTED_FLAG:
        raise SecurityError("DATA packet is not encrypted")
    cipher = ChaCha20Poly1305(session_key)
    try:
        payload = cipher.decrypt(
            _packet_nonce(session_key, packet.connection_id, packet.packet_number),
            packet.payload,
            _data_aad(packet),
        )
    except InvalidTag as error:
        raise SecurityError("DATA authentication failed") from error
    return replace(packet, payload=payload)


def sign_ack(packet, session_key):
    return replace(packet, auth_tag=_hmac(session_key, b"ACK" + _ack_data(packet)))


def verify_ack(packet, session_key):
    expected = _hmac(session_key, b"ACK" + _ack_data(packet))
    if not hmac.compare_digest(packet.auth_tag, expected):
        raise SecurityError("ACK authentication failed")


def sign_close(packet, session_key, role=b"client"):
    return replace(
        packet,
        auth_tag=_hmac(session_key, b"CLOSE-" + role + _close_data(packet)),
    )


def verify_close(packet, session_key, role=b"client"):
    expected = _hmac(session_key, b"CLOSE-" + role + _close_data(packet))
    if not hmac.compare_digest(packet.auth_tag, expected):
        raise SecurityError("CLOSE authentication failed")


def _hmac(key, data):
    return hmac.new(key, data, hashlib.sha256).digest()


def _handshake_data(packet):
    return struct.pack(
        "!BQQHH16s",
        VERSION,
        packet.connection_id,
        packet.packet_number,
        packet.flags,
        packet.receive_window,
        packet.nonce,
    )


def _data_aad(packet):
    return struct.pack(
        "!4sBHQQ16sHHHBBIQ",
        b"DART",
        VERSION,
        packet.flags,
        packet.connection_id,
        packet.packet_number,
        packet.message_id.bytes,
        packet.channel_id,
        packet.fragment_index,
        packet.fragment_count,
        packet.reliability,
        packet.priority,
        packet.deadline_ms or 0,
        packet.created_at_ms,
    )


def _ack_data(packet):
    return struct.pack(
        "!B H Q Q Q Q H",
        VERSION,
        packet.flags,
        packet.connection_id,
        packet.packet_number,
        packet.largest_acknowledged,
        packet.ack_bitmap,
        packet.receive_window,
    )


def _close_data(packet):
    return struct.pack(
        "!B H Q Q",
        VERSION,
        packet.flags,
        packet.connection_id,
        packet.packet_number,
    )


def _packet_nonce(session_key, connection_id, packet_number):
    data = b"DART-NONCE" + struct.pack("!QQ", connection_id, packet_number)
    return _hmac(session_key, data)[:12]
