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


if __name__ == "__main__":
    unittest.main()
