import unittest

from dart.message import MessageReassembler, fragment_message
from dart.packet import MAX_PAYLOAD_BYTES, PacketError, Reliability


class FragmentationTests(unittest.TestCase):
    def make_packets(self, data):
        return fragment_message(
            data,
            connection_id=123,
            first_packet_number=10,
            reliability=Reliability.RELIABLE,
        )

    def test_small_message_uses_one_fragment(self):
        packets = self.make_packets(b"hello")

        self.assertEqual(len(packets), 1)
        self.assertEqual(packets[0].payload, b"hello")
        self.assertEqual(packets[0].fragment_index, 0)
        self.assertEqual(packets[0].fragment_count, 1)

    def test_large_message_is_split_and_reassembled(self):
        original = b"x" * (MAX_PAYLOAD_BYTES * 2 + 25)
        packets = self.make_packets(original)
        reassembler = MessageReassembler()

        result = None
        for packet in packets:
            result = reassembler.add(packet)

        self.assertEqual(len(packets), 3)
        self.assertEqual(result, original)

    def test_fragments_can_arrive_out_of_order(self):
        original = b"a" * (MAX_PAYLOAD_BYTES + 10)
        packets = self.make_packets(original)
        reassembler = MessageReassembler()

        self.assertIsNone(reassembler.add(packets[1]))
        self.assertEqual(reassembler.add(packets[0]), original)

    def test_duplicate_fragment_is_not_delivered_twice(self):
        packets = self.make_packets(b"hello")
        reassembler = MessageReassembler()

        self.assertEqual(reassembler.add(packets[0]), b"hello")
        self.assertIsNone(reassembler.add(packets[0]))

    def test_different_fragment_metadata_is_rejected(self):
        original = b"x" * (MAX_PAYLOAD_BYTES + 10)
        packets = self.make_packets(original)
        changed_packet = packets[1].__class__(
            **{**packets[1].__dict__, "priority": 5}
        )
        reassembler = MessageReassembler()
        reassembler.add(packets[0])

        with self.assertRaisesRegex(PacketError, "different metadata"):
            reassembler.add(changed_packet)

    def test_incomplete_partial_message_expires(self):
        packets = fragment_message(
            b"x" * (MAX_PAYLOAD_BYTES + 10),
            connection_id=123,
            first_packet_number=1,
            reliability=Reliability.PARTIAL,
            deadline_ms=50,
            created_at_ms=1000,
        )
        reassembler = MessageReassembler()
        reassembler.add(packets[0])

        expired = reassembler.expire(1050)

        self.assertEqual(expired, [(123, packets[0].message_id)])
        self.assertEqual(reassembler.incomplete, {})

    def test_inactive_unreliable_message_expires(self):
        packets = fragment_message(
            b"x" * (MAX_PAYLOAD_BYTES + 10),
            connection_id=123,
            first_packet_number=1,
            reliability=Reliability.UNRELIABLE,
        )
        reassembler = MessageReassembler()
        reassembler.add(packets[0], now_ms=1000)

        expired = reassembler.expire(1100, stale_after_ms=100)

        self.assertEqual(expired, [(123, packets[0].message_id)])

    def test_inactive_reliable_message_does_not_expire(self):
        packets = self.make_packets(b"x" * (MAX_PAYLOAD_BYTES + 10))
        reassembler = MessageReassembler()
        reassembler.add(packets[0], now_ms=1000)

        expired = reassembler.expire(100000, stale_after_ms=100)

        self.assertEqual(expired, [])
        self.assertEqual(reassembler.incomplete_messages(123), 1)

    def test_completed_history_is_bounded(self):
        reassembler = MessageReassembler(max_completed=1)
        first = self.make_packets(b"first")[0]
        second = self.make_packets(b"second")[0]

        reassembler.add(first)
        reassembler.add(second)

        self.assertNotIn((first.connection_id, first.message_id), reassembler.completed)
        self.assertIn((second.connection_id, second.message_id), reassembler.completed)

    def test_connection_cleanup_removes_completed_state(self):
        packet = self.make_packets(b"hello")[0]
        reassembler = MessageReassembler()
        reassembler.add(packet)

        reassembler.remove_connection(packet.connection_id)

        self.assertEqual(reassembler.completed, set())

    def test_buffered_fragment_count_changes_after_completion(self):
        packets = self.make_packets(b"x" * (MAX_PAYLOAD_BYTES + 10))
        reassembler = MessageReassembler()

        reassembler.add(packets[0])
        self.assertEqual(reassembler.buffered_fragments(123), 1)
        self.assertEqual(reassembler.incomplete_messages(123), 1)

        reassembler.add(packets[1])
        self.assertEqual(reassembler.buffered_fragments(123), 0)
        self.assertEqual(reassembler.incomplete_messages(123), 0)


if __name__ == "__main__":
    unittest.main()
