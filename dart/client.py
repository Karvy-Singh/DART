"""Small reusable DART client used by the command-line sender."""

import math
import socket
import time
import uuid

from .congestion import CongestionController
from .connection import Connection, ConnectionState
from .message import fragment_message
from .pacing import Pacer
from .packet import (
    MAX_DATAGRAM_BYTES,
    AckPacket,
    ClosePacket,
    HelloAckPacket,
    HelloPacket,
    PacketError,
    Reliability,
    decode_packet,
    encode_packet,
)
from .rtt import RttEstimator


class DartClient:
    def __init__(
        self,
        sock,
        destination,
        maximum_window=8,
        timeout_ms=250,
        estimated_rtt_ms=100,
        max_attempts=10,
    ):
        connection_id = uuid.uuid4().int & ((1 << 64) - 1) or 1
        self.sock = sock
        self.destination = destination
        self.connection = Connection(connection_id)
        self.maximum_window = maximum_window
        self.max_attempts = max_attempts
        self.rtt = RttEstimator(estimated_rtt_ms, timeout_ms)
        self.congestion = CongestionController(maximum_window)
        self.pacer = Pacer()
        self.next_packet_number = 1
        self.failed = False

    def connect(self):
        """Exchange HELLO packets and learn the receiver's flow window."""
        self.connection.start_handshake()
        hello = HelloPacket(
            connection_id=self.connection.connection_id,
            packet_number=0,
            receive_window=self.maximum_window,
        )
        raw = encode_packet(hello)

        for attempt in range(1, self.max_attempts + 1):
            self.sock.sendto(raw, self.destination)
            self.sock.settimeout(self.rtt.timeout_ms / 1000)
            try:
                reply, peer = self.sock.recvfrom(MAX_DATAGRAM_BYTES + 1)
            except socket.timeout:
                self.rtt.packet_timed_out()
                continue

            if peer != self.destination:
                continue
            try:
                packet = decode_packet(reply)
            except PacketError:
                continue
            if (
                isinstance(packet, HelloAckPacket)
                and packet.connection_id == self.connection.connection_id
            ):
                self.connection.establish(packet.receive_window)
                print(
                    f"[SENDER  ] connected; receiver window={packet.receive_window}, "
                    f"handshake attempts={attempt}",
                    flush=True,
                )
                return

        raise ConnectionError("DART handshake failed")

    def send(
        self,
        data,
        reliability,
        deadline_ms=None,
        priority=0,
        created_at_ms=None,
        local_deadline_ms=None,
    ):
        """Send one complete application message."""
        if self.connection.state is not ConnectionState.ESTABLISHED:
            raise ConnectionError("DART connection is not established")
        if self.failed:
            raise ConnectionError("DART connection recovery has failed")
        if created_at_ms is None:
            created_at_ms = int(time.time() * 1000)
        if reliability == Reliability.PARTIAL and local_deadline_ms is None:
            local_deadline_ms = int(time.monotonic() * 1000) + deadline_ms
        expires_at = (
            local_deadline_ms / 1000
            if reliability == Reliability.PARTIAL
            else None
        )

        packets = fragment_message(
            data,
            connection_id=self.connection.connection_id,
            first_packet_number=self.next_packet_number,
            reliability=reliability,
            deadline_ms=deadline_ms,
            priority=priority,
            created_at_ms=created_at_ms,
        )
        self.next_packet_number += len(packets)

        if reliability == Reliability.UNRELIABLE:
            for packet in packets:
                self._send_raw(encode_packet(packet))
            return "unconfirmed"

        next_packet = 0
        delivered_count = 0
        in_flight = {}

        while delivered_count < len(packets):
            send_limit = min(
                self.maximum_window,
                self.connection.peer_window,
                self.congestion.window,
            )

            if expires_at is not None:
                remaining_ms = (expires_at - time.monotonic()) * 1000
                packets_left = len(packets) - delivered_count
                rounds_left = math.ceil(packets_left / send_limit)
                if remaining_ms < self.rtt.rtt_ms * rounds_left:
                    self._drain(in_flight)
                    return "expired"

            while next_packet < len(packets) and len(in_flight) < send_limit:
                packet = packets[next_packet]
                raw = encode_packet(packet)
                sent_at = self._send_raw(raw)
                in_flight[packet.packet_number] = {
                    "packet": packet,
                    "raw": raw,
                    "attempts": 1,
                    "sent_at": sent_at,
                }
                next_packet += 1

            now = time.monotonic()
            next_timeout = min(
                state["sent_at"] + self.rtt.timeout_ms / 1000
                for state in in_flight.values()
            )
            wait_seconds = max(0.001, next_timeout - now)
            if expires_at is not None:
                deadline_wait = expires_at - time.monotonic()
                wait_seconds = min(wait_seconds, max(0.001, deadline_wait))
            self.sock.settimeout(wait_seconds)

            try:
                raw_ack, peer = self.sock.recvfrom(MAX_DATAGRAM_BYTES + 1)
            except socket.timeout:
                raw_ack = None
                peer = None

            if raw_ack is not None and peer == self.destination:
                try:
                    ack = decode_packet(raw_ack)
                except PacketError:
                    ack = None
                if (
                    isinstance(ack, AckPacket)
                    and ack.connection_id == self.connection.connection_id
                ):
                    acknowledged = [
                        number for number in in_flight if ack.acknowledges(number)
                    ]
                    for number in acknowledged:
                        state = in_flight.pop(number)
                        if state["attempts"] == 1:
                            measured_ms = (
                                time.monotonic() - state["sent_at"]
                            ) * 1000
                            self.rtt.add_measurement(measured_ms)
                        delivered_count += 1
                    self.congestion.packets_acked(len(acknowledged))

            now = time.monotonic()
            timed_out = [
                state
                for state in in_flight.values()
                if now - state["sent_at"] >= self.rtt.timeout_ms / 1000
            ]
            if not timed_out:
                continue

            if any(state["attempts"] >= self.max_attempts for state in timed_out):
                self.failed = True
                return "failed"

            self.rtt.packet_timed_out()
            self.congestion.packet_loss()
            for state in timed_out:
                state["attempts"] += 1
                state["sent_at"] = self._send_raw(state["raw"])

        return "delivered"

    def close(self):
        self.connection.start_close()
        packet = ClosePacket(
            connection_id=self.connection.connection_id,
            packet_number=self.next_packet_number,
        )
        raw = encode_packet(packet)
        for _ in range(3):
            self.sock.sendto(raw, self.destination)
            self.sock.settimeout(self.rtt.timeout_ms / 1000)
            try:
                reply, peer = self.sock.recvfrom(MAX_DATAGRAM_BYTES + 1)
            except socket.timeout:
                continue
            if peer != self.destination:
                continue
            try:
                response = decode_packet(reply)
            except PacketError:
                continue
            if (
                isinstance(response, ClosePacket)
                and response.connection_id == self.connection.connection_id
            ):
                break
        self.connection.finish_close()

    def _send_raw(self, raw):
        peer_window = self.connection.peer_window or self.maximum_window
        active_window = max(1, min(self.congestion.window, peer_window))
        interval_ms = self.rtt.rtt_ms / active_window
        self.pacer.wait(interval_ms)
        self.sock.sendto(raw, self.destination)
        return time.monotonic()

    def _drain(self, in_flight):
        """Briefly collect ACKs before the next scheduled message starts."""
        wait_until = time.monotonic() + min(self.rtt.timeout_ms, 1000) / 1000
        while in_flight and time.monotonic() < wait_until:
            self.sock.settimeout(max(0.001, wait_until - time.monotonic()))
            try:
                raw_ack, peer = self.sock.recvfrom(MAX_DATAGRAM_BYTES + 1)
            except socket.timeout:
                return
            if peer != self.destination:
                continue
            try:
                ack = decode_packet(raw_ack)
            except PacketError:
                continue
            if (
                not isinstance(ack, AckPacket)
                or ack.connection_id != self.connection.connection_id
            ):
                continue
            for number in list(in_flight):
                if ack.acknowledges(number):
                    del in_flight[number]
