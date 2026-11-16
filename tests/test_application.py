import unittest

from dart.application import decode_message, encode_file, encode_text


class ApplicationMessageTests(unittest.TestCase):
    def test_text_round_trip(self):
        encoded = encode_text("hello DART")

        self.assertEqual(decode_message(encoded), ("text", None, "hello DART"))

    def test_binary_file_round_trip(self):
        encoded = encode_file("photo.bin", b"\x00\xff\x10")

        self.assertEqual(
            decode_message(encoded),
            ("file", "photo.bin", b"\x00\xff\x10"),
        )

    def test_sender_removes_directories_from_filename(self):
        encoded = encode_file("some/folder/report.txt", b"report")

        self.assertEqual(
            decode_message(encoded),
            ("file", "report.txt", b"report"),
        )

    def test_unknown_message_type_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unknown"):
            decode_message(b"\x63bad")

    def test_unsafe_received_filename_is_rejected(self):
        message = b"\x02\x00\x02..file data"

        with self.assertRaisesRegex(ValueError, "unsafe"):
            decode_message(message)


if __name__ == "__main__":
    unittest.main()
