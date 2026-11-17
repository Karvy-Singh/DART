import unittest
import uuid
from dataclasses import replace

from dart.packet import AckPacket, ClosePacket, DataPacket, HelloAckPacket, HelloPacket, Reliability
from dart.security import (
    SecurityError,
    decrypt_data,
    derive_session_key,
    encrypt_data,
    parse_key,
    sign_ack,
    sign_close,
    sign_hello,
    sign_hello_ack,
    verify_ack,
    verify_close,
    verify_hello,
    verify_hello_ack,
)


class SecurityTests(unittest.TestCase):
    def setUp(self):
        self.psk = bytes.fromhex("11" * 32)
        self.client_nonce = b"c" * 16
        self.server_nonce = b"s" * 16
        self.session_key = derive_session_key(
            self.psk,
            10,
            self.client_nonce,
            self.server_nonce,
        )

    def test_key_parser_requires_32_bytes(self):
        self.assertEqual(parse_key("11" * 32), self.psk)
        with self.assertRaises(SecurityError):
            parse_key("abcd")

    def test_handshake_authentication(self):
        hello = sign_hello(HelloPacket(10, 0, 8, self.client_nonce), self.psk)
        reply = sign_hello_ack(
            HelloAckPacket(10, 0, 4, self.server_nonce),
            self.psk,
            self.client_nonce,
        )

        verify_hello(hello, self.psk)
        verify_hello_ack(reply, self.psk, self.client_nonce)
        with self.assertRaises(SecurityError):
            verify_hello(replace(hello, receive_window=9), self.psk)

    def test_data_is_encrypted_and_metadata_is_authenticated(self):
        packet = DataPacket(
            connection_id=10,
            packet_number=1,
            message_id=uuid.uuid4(),
            channel_id=0,
            fragment_index=0,
            fragment_count=1,
            reliability=Reliability.RELIABLE,
            priority=2,
            deadline_ms=None,
            created_at_ms=0,
            payload=b"secret payload",
        )

        encrypted = encrypt_data(packet, self.session_key)

        self.assertNotIn(packet.payload, encrypted.payload)
        self.assertEqual(decrypt_data(encrypted, self.session_key).payload, packet.payload)
        with self.assertRaises(SecurityError):
            decrypt_data(replace(encrypted, priority=3), self.session_key)

    def test_ack_and_close_are_authenticated(self):
        ack = sign_ack(AckPacket(10, 2, 1, receive_window=4), self.session_key)
        close = sign_close(ClosePacket(10, 3), self.session_key, role=b"server")

        verify_ack(ack, self.session_key)
        verify_close(close, self.session_key, role=b"server")
        with self.assertRaises(SecurityError):
            verify_close(close, self.session_key, role=b"client")
        with self.assertRaises(SecurityError):
            verify_ack(replace(ack, receive_window=5), self.session_key)


if __name__ == "__main__":
    unittest.main()
