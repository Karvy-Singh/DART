import unittest

from dart.connection import Connection, ConnectionState


class ConnectionTests(unittest.TestCase):
    def test_complete_connection_lifecycle(self):
        connection = Connection(connection_id=10)

        self.assertEqual(connection.state, ConnectionState.CLOSED)
        self.assertIsNone(connection.peer_window)

        connection.start_handshake()
        self.assertEqual(connection.state, ConnectionState.HANDSHAKING)

        connection.establish(peer_window=64)
        self.assertEqual(connection.state, ConnectionState.ESTABLISHED)
        self.assertEqual(connection.peer_window, 64)

        connection.start_close()
        self.assertEqual(connection.state, ConnectionState.DRAINING)

        connection.finish_close()
        self.assertEqual(connection.state, ConnectionState.CLOSED)

    def test_methods_reject_illegal_transitions(self):
        connection = Connection(connection_id=10)

        with self.assertRaises(ValueError):
            connection.establish(64)
        with self.assertRaises(ValueError):
            connection.start_close()
        with self.assertRaises(ValueError):
            connection.finish_close()

        connection.start_handshake()
        with self.assertRaises(ValueError):
            connection.start_handshake()

    def test_establish_rejects_invalid_peer_window(self):
        for peer_window in (0, 65536, True):
            with self.subTest(peer_window=peer_window):
                connection = Connection(connection_id=10)
                connection.start_handshake()

                with self.assertRaisesRegex(ValueError, "Peer window"):
                    connection.establish(peer_window)
                self.assertEqual(connection.state, ConnectionState.HANDSHAKING)


if __name__ == "__main__":
    unittest.main()
