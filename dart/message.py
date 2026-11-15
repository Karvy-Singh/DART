"""Simple message fragmentation and reassembly for DART v2."""

import math
import uuid

from .packet import DataPacket, MAX_PAYLOAD_BYTES, PacketError, Reliability


def fragment_message(
    data,
    connection_id,
    first_packet_number,
    reliability,
    deadline_ms=None,
    channel_id=0,
    priority=0,
):
    """Split one bytes message into a list of DATA packets."""
    if not isinstance(data, bytes):
        raise PacketError("Message data must be bytes")

    fragment_count = max(1, math.ceil(len(data) / MAX_PAYLOAD_BYTES))
    if fragment_count > 65535:
        raise PacketError("Message needs too many fragments")

    message_id = uuid.uuid4()
    packets = []

    for fragment_index in range(fragment_count):
        start = fragment_index * MAX_PAYLOAD_BYTES
        end = start + MAX_PAYLOAD_BYTES
        payload = data[start:end]

        packets.append(
            DataPacket(
                connection_id=connection_id,
                packet_number=first_packet_number + fragment_index,
                message_id=message_id,
                channel_id=channel_id,
                fragment_index=fragment_index,
                fragment_count=fragment_count,
                reliability=reliability,
                priority=priority,
                deadline_ms=deadline_ms,
                payload=payload,
            )
        )

    return packets


class MessageReassembler:
    """Collect DATA fragments and return complete messages."""

    def __init__(self):
        self.incomplete = {}
        self.completed = set()

    def add(self, packet):
        """Add one fragment and return bytes when its message is complete."""
        if not isinstance(packet, DataPacket):
            raise PacketError("Reassembler only accepts DATA packets")
        if packet.fragment_count < 1 or not (
            0 <= packet.fragment_index < packet.fragment_count
        ):
            raise PacketError("Fragment numbers are invalid")

        message_key = (packet.connection_id, packet.message_id)
        if message_key in self.completed:
            return None

        if message_key not in self.incomplete:
            self.incomplete[message_key] = {
                "fragment_count": packet.fragment_count,
                "channel_id": packet.channel_id,
                "reliability": packet.reliability,
                "deadline_ms": packet.deadline_ms,
                "priority": packet.priority,
                "fragments": {},
            }

        message = self.incomplete[message_key]
        if (
            packet.fragment_count != message["fragment_count"]
            or packet.channel_id != message["channel_id"]
            or packet.reliability != message["reliability"]
            or packet.deadline_ms != message["deadline_ms"]
            or packet.priority != message["priority"]
        ):
            raise PacketError("Fragments for one message have different metadata")

        if packet.fragment_index not in message["fragments"]:
            message["fragments"][packet.fragment_index] = packet.payload

        if len(message["fragments"]) != message["fragment_count"]:
            return None

        complete_data = b"".join(
            message["fragments"][index]
            for index in range(message["fragment_count"])
        )
        del self.incomplete[message_key]
        self.completed.add(message_key)
        return complete_data
