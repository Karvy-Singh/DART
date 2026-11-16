"""Simple DART v2 sender. Start receiver.py before running this file."""

import argparse
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
):
    """Send one text message, one fragment at a time."""
    connection_id = uuid.uuid4().int & ((1 << 64) - 1)
    connection_id = connection_id or 1
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
    total_attempts = 0
    rtt = RttEstimator(estimated_rtt_ms, timeout_ms)

    print(
        f"[SENDER  ] connection={connection_id}, mode={mode}, "
        f"fragments={len(packets)}",
        flush=True,
    )

    for packet in packets:
        raw = encode_packet(packet)
        fragment_number = packet.fragment_index + 1

        if mode == "unreliable":
            sock.sendto(raw, destination)
            total_attempts += 1
            print(
                f"[SENDER  ] sent fragment {fragment_number}/{len(packets)} once",
                flush=True,
            )
            continue

        fragment_delivered = False

        for attempt in range(1, max_attempts + 1):
            if expires_at is not None:
                remaining_ms = (expires_at - time.monotonic()) * 1000
                fragments_left = len(packets) - packet.fragment_index
                estimated_delivery_ms = rtt.rtt_ms * fragments_left
                if remaining_ms < estimated_delivery_ms:
                    print("[SENDER  ] ABANDON: not enough time before deadline")
                    return 2

            sent_at = time.monotonic()
            sock.sendto(raw, destination)
            total_attempts += 1
            print(
                f"[SENDER  ] sent fragment {fragment_number}/{len(packets)}, "
                f"attempt {attempt}",
                flush=True,
            )

            wait_seconds = rtt.timeout_ms / 1000
            if expires_at is not None:
                wait_seconds = min(
                    wait_seconds,
                    max(0, expires_at - time.monotonic()),
                )
            wait_until = time.monotonic() + wait_seconds

            while time.monotonic() < wait_until:
                sock.settimeout(max(0.001, wait_until - time.monotonic()))
                try:
                    raw_ack, peer = sock.recvfrom(MAX_DATAGRAM_BYTES + 1)
                except socket.timeout:
                    break

                if peer != destination:
                    continue

                try:
                    ack = decode_packet(raw_ack)
                except PacketError:
                    continue

                if (
                    isinstance(ack, AckPacket)
                    and ack.connection_id == connection_id
                    and ack.acknowledges(packet.packet_number)
                ):
                    fragment_delivered = True
                    break

            if fragment_delivered:
                # A retransmitted packet gives an ambiguous RTT measurement.
                if attempt == 1:
                    measured_rtt_ms = (time.monotonic() - sent_at) * 1000
                    rtt.add_measurement(measured_rtt_ms)
                print(
                    f"[SENDER  ] ACK for fragment "
                    f"{fragment_number}/{len(packets)} "
                    f"(RTT={rtt.rtt_ms:.0f}ms, timeout={rtt.timeout_ms:.0f}ms)",
                    flush=True,
                )
                break

            rtt.packet_timed_out()
            print("[SENDER  ] no ACK, retrying", flush=True)

        if not fragment_delivered:
            print(f"[SENDER  ] FAILED on fragment {fragment_number}")
            return 1

    elapsed_ms = (time.monotonic() - started) * 1000
    if mode == "unreliable":
        print("[SENDER  ] finished: delivery is not confirmed")
    else:
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
    args = parser.parse_args()

    if min(
        args.deadline_ms,
        args.timeout_ms,
        args.estimated_rtt_ms,
        args.max_attempts,
    ) <= 0:
        parser.error("Timing and retry settings must be positive")
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
            )
    except (OSError, PacketError) as error:
        print(f"[SENDER  ] ERROR: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
