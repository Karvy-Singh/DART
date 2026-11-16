"""Simple DART v2 sender. Start receiver.py before running this file."""

import argparse
import math
import socket
import time
import uuid

from dart import (
    MAX_DATAGRAM_BYTES,
    AckPacket,
    PacketError,
    Reliability,
    RttEstimator,
    decode_packet,
    encode_packet,
    fragment_message,
)


MODE_NAMES = {
    "unreliable": Reliability.UNRELIABLE,
    "partial": Reliability.PARTIAL,
    "reliable": Reliability.RELIABLE,
}


def send_message(
    sock,
    destination,
    message,
    mode,
    deadline_ms,
    timeout_ms,
    estimated_rtt_ms,
    max_attempts,
    window_size,
):
    """Send one text message with a small fixed sliding window."""
    connection_id = uuid.uuid4().int & ((1 << 64) - 1) or 1
    reliability = MODE_NAMES[mode]
    packets = fragment_message(
        message.encode("utf-8"),
        connection_id=connection_id,
        first_packet_number=0,
        reliability=reliability,
        deadline_ms=deadline_ms if mode == "partial" else None,
    )

    started = time.monotonic()
    expires_at = started + deadline_ms / 1000 if mode == "partial" else None
    rtt = RttEstimator(estimated_rtt_ms, timeout_ms)
    total_attempts = 0

    print(
        f"[SENDER  ] connection={connection_id}, mode={mode}, "
        f"fragments={len(packets)}, window={window_size}",
        flush=True,
    )

    # Unreliable packets are sent once and do not need a window or ACKs.
    if mode == "unreliable":
        for packet in packets:
            sock.sendto(encode_packet(packet), destination)
            print(
                f"[SENDER  ] sent fragment "
                f"{packet.fragment_index + 1}/{len(packets)} once",
                flush=True,
            )
        print("[SENDER  ] finished: delivery is not confirmed")
        return 0

    next_packet = 0
    delivered_count = 0
    in_flight = {}

    while delivered_count < len(packets):
        if expires_at is not None:
            remaining_ms = (expires_at - time.monotonic()) * 1000
            packets_left = len(packets) - delivered_count
            rounds_left = math.ceil(packets_left / window_size)
            if remaining_ms < rtt.rtt_ms * rounds_left:
                print("[SENDER  ] ABANDON: not enough time before deadline")
                return 2

        # Fill all free places in the window.
        while next_packet < len(packets) and len(in_flight) < window_size:
            packet = packets[next_packet]
            raw = encode_packet(packet)
            sock.sendto(raw, destination)
            in_flight[packet.packet_number] = {
                "packet": packet,
                "raw": raw,
                "attempts": 1,
                "sent_at": time.monotonic(),
            }
            total_attempts += 1
            next_packet += 1
            print(
                f"[SENDER  ] sent fragment "
                f"{packet.fragment_index + 1}/{len(packets)}",
                flush=True,
            )

        # Wait for an ACK, but never wait past the next packet timeout.
        now = time.monotonic()
        next_timeout = min(
            state["sent_at"] + rtt.timeout_ms / 1000
            for state in in_flight.values()
        )
        wait_seconds = max(0.001, next_timeout - now)
        if expires_at is not None:
            wait_seconds = min(wait_seconds, max(0.001, expires_at - now))
        sock.settimeout(wait_seconds)

        try:
            raw_ack, peer = sock.recvfrom(MAX_DATAGRAM_BYTES + 1)
        except socket.timeout:
            raw_ack = None
            peer = None

        if raw_ack is not None and peer == destination:
            try:
                ack = decode_packet(raw_ack)
            except PacketError:
                ack = None

            if isinstance(ack, AckPacket) and ack.connection_id == connection_id:
                acknowledged = [
                    number for number in in_flight if ack.acknowledges(number)
                ]

                for number in acknowledged:
                    state = in_flight.pop(number)
                    if state["attempts"] == 1:
                        measured_ms = (
                            time.monotonic() - state["sent_at"]
                        ) * 1000
                        rtt.add_measurement(measured_ms)
                    delivered_count += 1

                if acknowledged:
                    print(
                        f"[SENDER  ] ACK covered {len(acknowledged)} packet(s) "
                        f"(RTT={rtt.rtt_ms:.0f}ms, "
                        f"timeout={rtt.timeout_ms:.0f}ms)",
                        flush=True,
                    )

        # Retry packets that have waited longer than the current timeout.
        now = time.monotonic()
        timed_out = [
            state
            for state in in_flight.values()
            if now - state["sent_at"] >= rtt.timeout_ms / 1000
        ]
        if timed_out:
            for state in timed_out:
                if state["attempts"] >= max_attempts:
                    fragment = state["packet"].fragment_index + 1
                    print(f"[SENDER  ] FAILED on fragment {fragment}")
                    return 1

            rtt.packet_timed_out()
            for state in timed_out:
                state["attempts"] += 1
                state["sent_at"] = time.monotonic()
                sock.sendto(state["raw"], destination)
                total_attempts += 1
                print(
                    f"[SENDER  ] retry fragment "
                    f"{state['packet'].fragment_index + 1}, "
                    f"attempt {state['attempts']}",
                    flush=True,
                )

    elapsed_ms = (time.monotonic() - started) * 1000
    print(
        f"[SENDER  ] complete after {total_attempts} transmission(s), "
        f"{elapsed_ms:.0f}ms",
    )
    return 0


def main():
    parser = argparse.ArgumentParser(description="Simple DART v2 sender")
    parser.add_argument("message", help="Text to send")
    parser.add_argument("--mode", choices=MODE_NAMES, default="partial")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9999)
    parser.add_argument("--deadline-ms", type=int, default=1500)
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=250,
        help="Initial ACK timeout; DART adjusts it after measuring RTT",
    )
    parser.add_argument(
        "--estimated-rtt-ms",
        type=int,
        default=100,
        help="Initial RTT guess used before the first measurement",
    )
    parser.add_argument("--max-attempts", type=int, default=10)
    parser.add_argument(
        "--window-size",
        type=int,
        default=4,
        help="Maximum number of unacknowledged fragments",
    )
    args = parser.parse_args()

    if min(
        args.deadline_ms,
        args.timeout_ms,
        args.estimated_rtt_ms,
        args.max_attempts,
        args.window_size,
    ) <= 0:
        parser.error("Timing, retry, and window settings must be positive")
    if not 1 <= args.port <= 65535:
        parser.error("Port must be between 1 and 65535")

    try:
        destination = (socket.gethostbyname(args.host), args.port)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            return send_message(
                sock,
                destination,
                args.message,
                args.mode,
                args.deadline_ms,
                args.timeout_ms,
                args.estimated_rtt_ms,
                args.max_attempts,
                args.window_size,
            )
    except (OSError, PacketError) as error:
        print(f"[SENDER  ] ERROR: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
