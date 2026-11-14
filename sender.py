"""DART sender: run in terminal 2 while receiver.py is running."""

import argparse
import socket
import time
import uuid

from protocol import (MAX_DATAGRAM_BYTES, MODES, PacketError, data_packet,
                      decode_packet, encode_packet)


def send_message(sock, destination, message, mode, deadline_ms,
                 timeout_ms, estimated_rtt_ms, max_attempts):
    message_id = uuid.uuid4().hex[:8]
    raw = encode_packet(data_packet(message_id, message, mode, deadline_ms))
    started = time.monotonic()
    expires_at = started + deadline_ms / 1000 if mode == "partial" else None
    attempts = 0
    print(f"[SENDER  ] ID={message_id}, mode={mode}, bytes={len(raw)}", flush=True)

    while attempts < max_attempts:
        if expires_at is not None:
            remaining_s = expires_at - time.monotonic()
            if remaining_s <= 0 or remaining_s * 1000 < estimated_rtt_ms:
                print(f"[SENDER  ] ABANDON: insufficient time before {deadline_ms}ms deadline")
                return 2

        attempts += 1
        sock.sendto(raw, destination)
        print(f"[SENDER  ] SEND attempt {attempts}", flush=True)
        if mode == "unreliable":
            print("[SENDER  ] finished: no ACK or retries (delivery unconfirmed)")
            return 0

        # Never wait beyond the remaining deadline for partial messages.
        wait_s = timeout_ms / 1000
        if expires_at is not None:
            wait_s = min(wait_s, max(0, expires_at - time.monotonic()))
        end_wait = time.monotonic() + wait_s
        while time.monotonic() < end_wait:
            sock.settimeout(max(0.001, end_wait - time.monotonic()))
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
            if ack["type"] == "ack" and ack["id"] == message_id:
                elapsed_ms = (time.monotonic() - started) * 1000
                if expires_at is not None and time.monotonic() > expires_at:
                    print(f"[SENDER  ] ACK too late ({elapsed_ms:.0f}ms); deadline missed")
                    return 2
                print(f"[SENDER  ] ACK received after {attempts} attempt(s), "
                      f"{elapsed_ms:.0f}ms elapsed")
                return 0

        print("[SENDER  ] no matching ACK within timeout", flush=True)

    print(f"[SENDER  ] FAILED after {max_attempts} attempt(s) "
          "(safety cap for this demo)")
    return 1


def main():
    parser = argparse.ArgumentParser(description="DART sender (educational UDP client)")
    parser.add_argument("message", help="Text to send")
    parser.add_argument("--mode", choices=MODES, default="partial")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9999)
    parser.add_argument("--deadline-ms", type=int, default=1500,
                        help="Only used for partial messages")
    parser.add_argument("--timeout-ms", type=int, default=250,
                        help="ACK wait per attempt")
    parser.add_argument("--estimated-rtt-ms", type=int, default=100,
                        help="Simplified predicted round-trip time for deadline decisions")
    parser.add_argument("--max-attempts", type=int, default=10,
                        help="Demo safety cap (not a true unbounded reliable guarantee)")
    args = parser.parse_args()
    if min(args.deadline_ms, args.timeout_ms, args.estimated_rtt_ms, args.max_attempts) <= 0:
        parser.error("All timing and retry settings must be positive")
    if not 1 <= args.port <= 65535:
        parser.error("Port must be 1..65535")

    try:
        destination = (socket.gethostbyname(args.host), args.port)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            return send_message(sock, destination, args.message, args.mode,
                                args.deadline_ms if args.mode == "partial" else None,
                                args.timeout_ms, args.estimated_rtt_ms, args.max_attempts)
    except (OSError, PacketError) as exc:
        print(f"[SENDER  ] ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
