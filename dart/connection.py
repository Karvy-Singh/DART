"""Small connection state machine for the DART handshake."""

from enum import Enum


class ConnectionState(Enum):
    CLOSED = "closed"
    HANDSHAKING = "handshaking"
    ESTABLISHED = "established"
    DRAINING = "draining"


class Connection:
    def __init__(self, connection_id):
        self.connection_id = connection_id
        self.state = ConnectionState.CLOSED
        self.peer_window = None

    def start_handshake(self):
        if self.state is not ConnectionState.CLOSED:
            raise ValueError("Handshake can only start from CLOSED")
        self.state = ConnectionState.HANDSHAKING

    def establish(self, peer_window):
        if self.state is not ConnectionState.HANDSHAKING:
            raise ValueError("Connection can only be established while HANDSHAKING")
        if type(peer_window) is not int or not 1 <= peer_window <= 65535:
            raise ValueError("Peer window must be between 1 and 65535")
        self.peer_window = peer_window
        self.state = ConnectionState.ESTABLISHED

    def start_close(self):
        if self.state is not ConnectionState.ESTABLISHED:
            raise ValueError("Close can only start from ESTABLISHED")
        self.state = ConnectionState.DRAINING

    def finish_close(self):
        if self.state is not ConnectionState.DRAINING:
            raise ValueError("Close can only finish while DRAINING")
        self.state = ConnectionState.CLOSED
