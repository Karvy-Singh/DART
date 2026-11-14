"""DART receiver: run this in terminal 1, then start sender.py in terminal 2."""

import argparse
import random
import socket
import time

from protocol import MAX_DATAGRAM_BYTES, PacketError, ack_packet, decode_packet, encode_packet


def main():
    parser = argparse.ArgumentParser(description="DART receiver (educational UDP server)")
    parser.add_argument("--host", default="127.0.0.1", help="Bind interface; defaults to localhost")
    parser.add_argument("--port", type=int, default=9999)
    parser.add_argument("--loss", type=float, default=0.0,
                        help="Simulated DATA packet loss, between 0 and 1")
    parser.add_argument("--ack-loss", type=float, default=0.0,
                        help="Simulated ACK packet loss, between 0 and 1")
    parser.add_argument("--drop-first", action="store_true",
                        help="Always drop the first copy of each message ID")
    parser.add_argument("--delay-ms", type=int, default=0,
                        help="Wait before processing each received datagram")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    if not (0 <= args.loss <= 1 and 0 <= args.ack_loss <= 1):
        parser.error("--loss and --ack-loss must be between 0 and 1")
    if args.delay_ms < 0 or not (1 <= args.port <= 65535):
        parser.error("--delay-ms must be >= 0 and port must be 1..65535")

    rng = random.Random(args.seed)
    seen_ids = set()     # A real implementation would expire old IDs
    dropped_once = set()

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind((args.host, args.port))
        print(f"[RECEIVER] listening on {args.host}:{args.port} (UDP)", flush=True)
        print(f"[RECEIVER] loss={args.loss:.0%}, ack-loss={args.ack_loss:.0%}, "
              f"drop-first={args.drop_first}, delay={args.delay_ms}ms", flush=True)
        try:
            while True:
                raw, address = sock.recvfrom(MAX_DATAGRAM_BYTES + 1)
                try:
                    packet = decode_packet(raw)
                except PacketError as exc:
                    print(f"[RECEIVER] ignored malformed packet from {address}: {exc}", flush=True)
                    continue
                if packet["type"] != "data":
                    continue

                mid = packet["id"]
                if args.drop_first and mid not in dropped_once:
                    dropped_once.add(mid)
                    print(f"[NETWORK ] dropped first copy of {mid}", flush=True)
                    continue
                if rng.random() < args.loss:
                    print(f"[NETWORK ] randomly dropped {mid}", flush=True)
                    continue
                if args.delay_ms:
                    time.sleep(args.delay_ms / 1000)

                if mid in seen_ids:
                    print(f"[RECEIVER] duplicate {mid}; ACK again (do not deliver twice)", flush=True)
                else:
                    seen_ids.add(mid)
                    print(f"[RECEIVER] delivered {mid}: {packet['data']!r} "
                          f"[{packet['mode']}]", flush=True)

                # Unreliable data is delivered, but does not require an ACK.
                if packet["mode"] == "unreliable":
                    continue
                if rng.random() < args.ack_loss:
                    print(f"[NETWORK ] ACK for {mid} lost", flush=True)
                    continue
                sock.sendto(encode_packet(ack_packet(mid)), address)
                print(f"[RECEIVER] ACK sent for {mid}", flush=True)
        except KeyboardInterrupt:
            print("\n[RECEIVER] stopped")


if __name__ == "__main__":
    main()
