"""Simple binary packet format for DART v4.

This module only knows how to turn packet objects into bytes and back again.
Networking, retries, and scheduling will be added in separate modules later.
"""

from dataclasses import dataclass
from enum import IntEnum
import struct
import uuid


MAGIC = b"DART"
VERSION = 4
MAX_DATAGRAM_BYTES = 1200
AUTH_TAG_BYTES = 32
HANDSHAKE_NONCE_BYTES = 16

# All numbers use network byte order (the ! at the start).
# Common: magic, version, packet type, flags, connection ID, packet number.
COMMON_HEADER = struct.Struct("!4sBBHQQ")

# DATA: message ID, channel, fragment index, fragment count, reliability,
# priority, deadline, creation time, payload length.
DATA_HEADER = struct.Struct("!16sHHHBBIQH")

# ACK: largest packet, bitmap, current receive window, authentication tag.
ACK_HEADER = struct.Struct("!QQH32s")

# HELLO: receive window, random nonce, authentication tag.
HANDSHAKE_HEADER = struct.Struct("!H16s32s")
CLOSE_HEADER = struct.Struct("!32s")

DATA_HEADER_BYTES = COMMON_HEADER.size + DATA_HEADER.size
ACK_PACKET_BYTES = COMMON_HEADER.size + ACK_HEADER.size
MAX_PAYLOAD_BYTES = MAX_DATAGRAM_BYTES - DATA_HEADER_BYTES


class PacketError(ValueError):
    """Raised when a packet is invalid."""


class PacketType(IntEnum):
    HELLO = 1
    HELLO_ACK = 2
    DATA = 3
    ACK = 4
    CLOSE = 5


class Reliability(IntEnum):
    UNRELIABLE = 0
    PARTIAL = 1
    RELIABLE = 2


@dataclass(frozen=True)
class HelloPacket:
    connection_id: int
    packet_number: int
    receive_window: int
    nonce: bytes = bytes(HANDSHAKE_NONCE_BYTES)
    auth_tag: bytes = bytes(AUTH_TAG_BYTES)
    flags: int = 0


@dataclass(frozen=True)
class HelloAckPacket:
    connection_id: int
    packet_number: int
    receive_window: int
    nonce: bytes = bytes(HANDSHAKE_NONCE_BYTES)
    auth_tag: bytes = bytes(AUTH_TAG_BYTES)
    flags: int = 0


@dataclass(frozen=True)
class DataPacket:
    connection_id: int
    packet_number: int
    message_id: uuid.UUID
    channel_id: int
    fragment_index: int
    fragment_count: int
    reliability: Reliability
    priority: int
    deadline_ms: int | None
    created_at_ms: int
    payload: bytes
    flags: int = 0


@dataclass(frozen=True)
class AckPacket:
    connection_id: int
    packet_number: int
    largest_acknowledged: int
    ack_bitmap: int = 0
    receive_window: int = 1
    auth_tag: bytes = bytes(AUTH_TAG_BYTES)
    flags: int = 0

    def acknowledges(self, packet_number):
        """Check whether this ACK includes a packet number."""
        if not valid_number(packet_number, 64):
            return False
        if packet_number == self.largest_acknowledged:
            return True

        distance = self.largest_acknowledged - packet_number
        if distance < 1 or distance > 64:
            return False

        bit = distance - 1
        return bool(self.ack_bitmap & (1 << bit))


@dataclass(frozen=True)
class ClosePacket:
    connection_id: int
    packet_number: int
    auth_tag: bytes = bytes(AUTH_TAG_BYTES)
    flags: int = 0


def valid_number(value, bits):
    """Return True when value fits in an unsigned integer of this size."""
    return type(value) is int and 0 <= value < (1 << bits)


def encode_packet(packet):
    """Convert a packet object into bytes for socket.sendto()."""
    packet_classes = (HelloPacket, HelloAckPacket, DataPacket, AckPacket, ClosePacket)
    if not isinstance(packet, packet_classes):
        raise PacketError("Expected a DART packet")

    if not valid_number(packet.connection_id, 64) or packet.connection_id == 0:
        raise PacketError("Connection ID must be a non-zero 64-bit number")
    if not valid_number(packet.packet_number, 64):
        raise PacketError("Packet number must be a 64-bit number")
    if not valid_number(packet.flags, 16):
        raise PacketError("Flags must be a 16-bit number")

    if isinstance(packet, (HelloPacket, HelloAckPacket)):
        if not valid_number(packet.receive_window, 16) or packet.receive_window == 0:
            raise PacketError("Receive window must be between 1 and 65535")
        if not isinstance(packet.nonce, bytes) or len(packet.nonce) != HANDSHAKE_NONCE_BYTES:
            raise PacketError("Handshake nonce must be 16 bytes")
        if not isinstance(packet.auth_tag, bytes) or len(packet.auth_tag) != AUTH_TAG_BYTES:
            raise PacketError("Authentication tag must be 32 bytes")

        if isinstance(packet, HelloPacket):
            packet_type = PacketType.HELLO
        else:
            packet_type = PacketType.HELLO_ACK

        common_bytes = COMMON_HEADER.pack(
            MAGIC,
            VERSION,
            packet_type,
            packet.flags,
            packet.connection_id,
            packet.packet_number,
        )
        return common_bytes + HANDSHAKE_HEADER.pack(
            packet.receive_window,
            packet.nonce,
            packet.auth_tag,
        )

    if isinstance(packet, DataPacket):
        packet_type = PacketType.DATA

        if not isinstance(packet.message_id, uuid.UUID):
            raise PacketError("Message ID must be a UUID")
        if not valid_number(packet.channel_id, 16):
            raise PacketError("Channel ID must be a 16-bit number")
        if not valid_number(packet.fragment_count, 16) or packet.fragment_count == 0:
            raise PacketError("Fragment count must be between 1 and 65535")
        if not valid_number(packet.fragment_index, 16):
            raise PacketError("Fragment index must be a 16-bit number")
        if packet.fragment_index >= packet.fragment_count:
            raise PacketError("Fragment index must be smaller than fragment count")
        if not isinstance(packet.reliability, Reliability):
            raise PacketError("Unknown reliability mode")
        if not valid_number(packet.priority, 8):
            raise PacketError("Priority must be an 8-bit number")

        if packet.reliability == Reliability.PARTIAL:
            if not valid_number(packet.deadline_ms, 32) or packet.deadline_ms == 0:
                raise PacketError("PARTIAL packets require a positive deadline")
            if not valid_number(packet.created_at_ms, 64) or packet.created_at_ms == 0:
                raise PacketError("PARTIAL packets require a creation time")
        elif packet.deadline_ms is not None:
            raise PacketError("Only PARTIAL packets may carry a deadline")
        elif not valid_number(packet.created_at_ms, 64):
            raise PacketError("Creation time must be a 64-bit number")

        if not isinstance(packet.payload, bytes):
            raise PacketError("Payload must be bytes")
        if len(packet.payload) > MAX_PAYLOAD_BYTES:
            raise PacketError("Payload exceeds the maximum packet size")

        common_bytes = COMMON_HEADER.pack(
            MAGIC,
            VERSION,
            packet_type,
            packet.flags,
            packet.connection_id,
            packet.packet_number,
        )
        data_bytes = DATA_HEADER.pack(
            packet.message_id.bytes,
            packet.channel_id,
            packet.fragment_index,
            packet.fragment_count,
            packet.reliability,
            packet.priority,
            packet.deadline_ms or 0,
            packet.created_at_ms,
            len(packet.payload),
        )
        return common_bytes + data_bytes + packet.payload

    if isinstance(packet, AckPacket):
        if not valid_number(packet.largest_acknowledged, 64):
            raise PacketError("Largest acknowledged must be a 64-bit number")
        if not valid_number(packet.ack_bitmap, 64):
            raise PacketError("ACK bitmap must be a 64-bit number")
        if not valid_number(packet.receive_window, 16) or packet.receive_window == 0:
            raise PacketError("Receive window must be between 1 and 65535")
        if not isinstance(packet.auth_tag, bytes) or len(packet.auth_tag) != AUTH_TAG_BYTES:
            raise PacketError("Authentication tag must be 32 bytes")

        common_bytes = COMMON_HEADER.pack(
            MAGIC,
            VERSION,
            PacketType.ACK,
            packet.flags,
            packet.connection_id,
            packet.packet_number,
        )
        ack_bytes = ACK_HEADER.pack(
            packet.largest_acknowledged,
            packet.ack_bitmap,
            packet.receive_window,
            packet.auth_tag,
        )
        return common_bytes + ack_bytes

    common_bytes = COMMON_HEADER.pack(
        MAGIC,
        VERSION,
        PacketType.CLOSE,
        packet.flags,
        packet.connection_id,
        packet.packet_number,
    )
    if not isinstance(packet.auth_tag, bytes) or len(packet.auth_tag) != AUTH_TAG_BYTES:
        raise PacketError("Authentication tag must be 32 bytes")
    return common_bytes + CLOSE_HEADER.pack(packet.auth_tag)


def decode_packet(raw):
    """Convert bytes received from a UDP socket back into a packet object."""
    if not isinstance(raw, bytes):
        raise PacketError("Packet must be bytes")
    if len(raw) > MAX_DATAGRAM_BYTES:
        raise PacketError("Packet is too large")
    if len(raw) < COMMON_HEADER.size:
        raise PacketError("Packet is shorter than the common header")

    magic, version, packet_type, flags, connection_id, packet_number = (
        COMMON_HEADER.unpack_from(raw)
    )

    if magic != MAGIC:
        raise PacketError("Invalid packet magic")
    if version != VERSION:
        raise PacketError("Unsupported packet version")
    if connection_id == 0:
        raise PacketError("Connection ID cannot be zero")

    body = raw[COMMON_HEADER.size:]

    if packet_type in (PacketType.HELLO, PacketType.HELLO_ACK):
        if len(body) != HANDSHAKE_HEADER.size:
            raise PacketError("Handshake packet has an invalid length")

        receive_window, nonce, auth_tag = HANDSHAKE_HEADER.unpack(body)
        if receive_window == 0:
            raise PacketError("Receive window must be between 1 and 65535")

        packet_class = HelloPacket if packet_type == PacketType.HELLO else HelloAckPacket
        return packet_class(
            connection_id=connection_id,
            packet_number=packet_number,
            receive_window=receive_window,
            nonce=nonce,
            auth_tag=auth_tag,
            flags=flags,
        )

    if packet_type == PacketType.DATA:
        if len(body) < DATA_HEADER.size:
            raise PacketError("DATA packet is too short")

        values = DATA_HEADER.unpack_from(body)
        message_id_bytes = values[0]
        channel_id = values[1]
        fragment_index = values[2]
        fragment_count = values[3]
        reliability_number = values[4]
        priority = values[5]
        deadline_number = values[6]
        created_at_ms = values[7]
        payload_length = values[8]
        payload = body[DATA_HEADER.size:]

        if len(payload) != payload_length:
            raise PacketError("DATA payload length does not match its header")
        if fragment_count == 0 or fragment_index >= fragment_count:
            raise PacketError("DATA packet has invalid fragment numbers")

        try:
            reliability = Reliability(reliability_number)
        except ValueError as error:
            raise PacketError("Unknown reliability mode") from error

        deadline_ms = deadline_number or None
        if reliability == Reliability.PARTIAL and deadline_ms is None:
            raise PacketError("PARTIAL packets require a positive deadline")
        if reliability == Reliability.PARTIAL and created_at_ms == 0:
            raise PacketError("PARTIAL packets require a creation time")
        if reliability != Reliability.PARTIAL and deadline_ms is not None:
            raise PacketError("Only PARTIAL packets may carry a deadline")

        return DataPacket(
            connection_id=connection_id,
            packet_number=packet_number,
            message_id=uuid.UUID(bytes=message_id_bytes),
            channel_id=channel_id,
            fragment_index=fragment_index,
            fragment_count=fragment_count,
            reliability=reliability,
            priority=priority,
            deadline_ms=deadline_ms,
            created_at_ms=created_at_ms,
            payload=payload,
            flags=flags,
        )

    if packet_type == PacketType.ACK:
        if len(body) != ACK_HEADER.size:
            raise PacketError("ACK packet has an invalid length")

        largest_acknowledged, ack_bitmap, receive_window, auth_tag = ACK_HEADER.unpack(body)
        if receive_window == 0:
            raise PacketError("Receive window must be between 1 and 65535")
        return AckPacket(
            connection_id=connection_id,
            packet_number=packet_number,
            largest_acknowledged=largest_acknowledged,
            ack_bitmap=ack_bitmap,
            receive_window=receive_window,
            auth_tag=auth_tag,
            flags=flags,
        )

    if packet_type == PacketType.CLOSE:
        if len(body) != CLOSE_HEADER.size:
            raise PacketError("CLOSE packet has an invalid length")
        (auth_tag,) = CLOSE_HEADER.unpack(body)
        return ClosePacket(
            connection_id=connection_id,
            packet_number=packet_number,
            auth_tag=auth_tag,
            flags=flags,
        )

    raise PacketError("Unknown packet type")
