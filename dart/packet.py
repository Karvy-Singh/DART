"""Simple binary packet format for DART v2.

This module only knows how to turn packet objects into bytes and back again.
Networking, retries, and scheduling will be added in separate modules later.
"""

from dataclasses import dataclass
from enum import IntEnum
import struct
import uuid


MAGIC = b"DART"
VERSION = 2
MAX_DATAGRAM_BYTES = 1200

# All numbers use network byte order (the ! at the start).
# Common: magic, version, packet type, flags, connection ID, packet number.
COMMON_HEADER = struct.Struct("!4sBBHQQ")

# DATA: message ID, channel, fragment index, fragment count, reliability,
# priority, deadline, payload length.
DATA_HEADER = struct.Struct("!16sHHHBBIH")

# ACK: largest received packet and a bitmap for the previous 64 packets.
ACK_HEADER = struct.Struct("!QQ")

DATA_HEADER_BYTES = COMMON_HEADER.size + DATA_HEADER.size
ACK_PACKET_BYTES = COMMON_HEADER.size + ACK_HEADER.size
MAX_PAYLOAD_BYTES = MAX_DATAGRAM_BYTES - DATA_HEADER_BYTES


class PacketError(ValueError):
    """Raised when a packet is invalid."""


class PacketType(IntEnum):
    DATA = 3
    ACK = 4


class Reliability(IntEnum):
    UNRELIABLE = 0
    PARTIAL = 1
    RELIABLE = 2


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
    payload: bytes
    flags: int = 0


@dataclass(frozen=True)
class AckPacket:
    connection_id: int
    packet_number: int
    largest_acknowledged: int
    ack_bitmap: int = 0
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


def valid_number(value, bits):
    """Return True when value fits in an unsigned integer of this size."""
    return type(value) is int and 0 <= value < (1 << bits)


def encode_packet(packet):
    """Convert a DataPacket or AckPacket into bytes for socket.sendto()."""
    if not isinstance(packet, (DataPacket, AckPacket)):
        raise PacketError("Expected a DataPacket or AckPacket")

    if not valid_number(packet.connection_id, 64) or packet.connection_id == 0:
        raise PacketError("Connection ID must be a non-zero 64-bit number")
    if not valid_number(packet.packet_number, 64):
        raise PacketError("Packet number must be a 64-bit number")
    if not valid_number(packet.flags, 16):
        raise PacketError("Flags must be a 16-bit number")

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
        elif packet.deadline_ms is not None:
            raise PacketError("Only PARTIAL packets may carry a deadline")

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
            len(packet.payload),
        )
        return common_bytes + data_bytes + packet.payload

    packet_type = PacketType.ACK
    if not valid_number(packet.largest_acknowledged, 64):
        raise PacketError("Largest acknowledged must be a 64-bit number")
    if not valid_number(packet.ack_bitmap, 64):
        raise PacketError("ACK bitmap must be a 64-bit number")

    common_bytes = COMMON_HEADER.pack(
        MAGIC,
        VERSION,
        packet_type,
        packet.flags,
        packet.connection_id,
        packet.packet_number,
    )
    ack_bytes = ACK_HEADER.pack(packet.largest_acknowledged, packet.ack_bitmap)
    return common_bytes + ack_bytes


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
        payload_length = values[7]
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
            payload=payload,
            flags=flags,
        )

    if packet_type == PacketType.ACK:
        if len(body) != ACK_HEADER.size:
            raise PacketError("ACK packet has an invalid length")

        largest_acknowledged, ack_bitmap = ACK_HEADER.unpack(body)
        return AckPacket(
            connection_id=connection_id,
            packet_number=packet_number,
            largest_acknowledged=largest_acknowledged,
            ack_bitmap=ack_bitmap,
            flags=flags,
        )

    raise PacketError("Unknown packet type")
