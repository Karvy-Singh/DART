import struct
import unittest
import uuid

from dart.packet import (
    COMMON_HEADER,
    DATA_HEADER_BYTES,
    MAX_DATAGRAM_BYTES,
    MAX_PAYLOAD_BYTES,
    AckPacket,
    ClosePacket,
    DataPacket,
    HelloAckPacket,
    HelloPacket,
    PacketError,
    PacketType,
    Reliability,
    decode_packet,
    encode_packet,
)


class HandshakePacketTests(unittest.TestCase):
    def test_packet_type_numbers(self):
        self.assertEqual(PacketType.HELLO, 1)
        self.assertEqual(PacketType.HELLO_ACK, 2)
        self.assertEqual(PacketType.DATA, 3)
        self.assertEqual(PacketType.ACK, 4)
        self.assertEqual(PacketType.CLOSE, 5)

    def test_hello_packets_round_trip(self):
        packets = (
            HelloPacket(10, 1, receive_window=64),
            HelloAckPacket(10, 2, receive_window=128, flags=1),
        )

        for packet in packets:
            with self.subTest(packet=packet):
                self.assertEqual(decode_packet(encode_packet(packet)), packet)

    def test_receive_window_must_be_in_range(self):
        for receive_window in (0, 65536, True):
            with self.subTest(receive_window=receive_window):
                with self.assertRaisesRegex(PacketError, "Receive window"):
                    encode_packet(HelloPacket(10, 1, receive_window))

    def test_zero_receive_window_is_rejected_when_decoding(self):
        raw = bytearray(encode_packet(HelloPacket(10, 1, 1)))
        struct.pack_into("!H", raw, COMMON_HEADER.size, 0)

        with self.assertRaisesRegex(PacketError, "Receive window"):
            decode_packet(bytes(raw))

    def test_close_packet_round_trip(self):
        packet = ClosePacket(10, 3, flags=2)

        self.assertEqual(decode_packet(encode_packet(packet)), packet)

    def test_close_packet_rejects_a_body(self):
        raw = encode_packet(ClosePacket(10, 3))

        with self.assertRaisesRegex(PacketError, "invalid length"):
            decode_packet(raw + b"extra")


class DataPacketTests(unittest.TestCase):
    def make_packet(self, **changes):
        values = {
            "connection_id": 10,
            "packet_number": 25,
            "message_id": uuid.UUID("12345678-1234-5678-1234-567812345678"),
            "channel_id": 3,
            "fragment_index": 1,
            "fragment_count": 4,
            "reliability": Reliability.PARTIAL,
            "priority": 7,
            "deadline_ms": 80,
            "created_at_ms": 1_700_000_000_000,
            "payload": b"frame fragment",
        }
        values.update(changes)
        return DataPacket(**values)

    def test_round_trip(self):
        packet = self.make_packet()

        encoded = encode_packet(packet)

        self.assertEqual(decode_packet(encoded), packet)

    def test_all_reliability_classes_round_trip(self):
        cases = (
            (Reliability.UNRELIABLE, None),
            (Reliability.PARTIAL, 150),
            (Reliability.RELIABLE, None),
        )
        for reliability, deadline_ms in cases:
            with self.subTest(reliability=reliability):
                packet = self.make_packet(
                    reliability=reliability,
                    deadline_ms=deadline_ms,
                )
                self.assertEqual(decode_packet(encode_packet(packet)), packet)

    def test_maximum_payload_fits_one_datagram(self):
        packet = self.make_packet(payload=b"x" * MAX_PAYLOAD_BYTES)

        encoded = encode_packet(packet)

        self.assertEqual(len(encoded), MAX_DATAGRAM_BYTES)
        self.assertEqual(len(encoded), DATA_HEADER_BYTES + MAX_PAYLOAD_BYTES)

    def test_oversized_payload_is_rejected(self):
        packet = self.make_packet(payload=b"x" * (MAX_PAYLOAD_BYTES + 1))

        with self.assertRaisesRegex(PacketError, "Payload exceeds"):
            encode_packet(packet)

    def test_partial_packet_requires_deadline(self):
        with self.assertRaisesRegex(PacketError, "require a positive"):
            encode_packet(self.make_packet(deadline_ms=None))

    def test_non_partial_packet_rejects_deadline(self):
        packet = self.make_packet(
            reliability=Reliability.RELIABLE,
            deadline_ms=80,
        )

        with self.assertRaisesRegex(PacketError, "Only PARTIAL"):
            encode_packet(packet)

    def test_fragment_index_must_be_in_range(self):
        packet = self.make_packet(fragment_index=4, fragment_count=4)

        with self.assertRaisesRegex(PacketError, "smaller than fragment count"):
            encode_packet(packet)

    def test_boolean_integer_field_is_rejected(self):
        with self.assertRaisesRegex(PacketError, "Channel ID"):
            encode_packet(self.make_packet(channel_id=True))


class AckPacketTests(unittest.TestCase):
    def test_round_trip(self):
        packet = AckPacket(
            connection_id=10,
            packet_number=30,
            largest_acknowledged=25,
            ack_bitmap=0b101,
        )

        self.assertEqual(decode_packet(encode_packet(packet)), packet)

    def test_ack_bitmap_covers_largest_and_predecessors(self):
        ack = AckPacket(
            connection_id=10,
            packet_number=30,
            largest_acknowledged=100,
            ack_bitmap=0b101,
        )

        self.assertTrue(ack.acknowledges(100))
        self.assertTrue(ack.acknowledges(99))
        self.assertFalse(ack.acknowledges(98))
        self.assertTrue(ack.acknowledges(97))
        self.assertFalse(ack.acknowledges(101))
        self.assertFalse(ack.acknowledges(35))


class MalformedPacketTests(unittest.TestCase):
    def valid_data(self):
        return encode_packet(
            DataPacket(
                connection_id=1,
                packet_number=2,
                message_id=uuid.uuid4(),
                channel_id=0,
                fragment_index=0,
                fragment_count=1,
                reliability=Reliability.RELIABLE,
                priority=0,
                deadline_ms=None,
                created_at_ms=0,
                payload=b"data",
            )
        )

    def test_short_packet_is_rejected(self):
        with self.assertRaisesRegex(PacketError, "shorter than the common"):
            decode_packet(b"DART")

    def test_invalid_magic_is_rejected(self):
        raw = bytearray(self.valid_data())
        raw[:4] = b"FAIL"

        with self.assertRaisesRegex(PacketError, "magic"):
            decode_packet(bytes(raw))

    def test_unknown_version_is_rejected(self):
        raw = bytearray(self.valid_data())
        raw[4] = 99

        with self.assertRaisesRegex(PacketError, "version"):
            decode_packet(bytes(raw))

    def test_unknown_packet_type_is_rejected(self):
        raw = bytearray(self.valid_data())
        raw[5] = 99

        with self.assertRaisesRegex(PacketError, "type"):
            decode_packet(bytes(raw))

    def test_payload_length_mismatch_is_rejected(self):
        raw = bytearray(self.valid_data())
        payload_length_offset = DATA_HEADER_BYTES - 2
        struct.pack_into("!H", raw, payload_length_offset, 100)

        with self.assertRaisesRegex(PacketError, "payload length"):
            decode_packet(bytes(raw))

    def test_ack_with_trailing_bytes_is_rejected(self):
        raw = encode_packet(
            AckPacket(
                connection_id=1,
                packet_number=2,
                largest_acknowledged=1,
            )
        )

        with self.assertRaisesRegex(PacketError, "invalid length"):
            decode_packet(raw + b"extra")


if __name__ == "__main__":
    unittest.main()
