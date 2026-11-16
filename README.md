# DART

DART (Deadline-Aware Reliable Transport) is an educational, message-oriented
transport protocol built over UDP. Its research goal is to make scheduling and
retransmission decisions using message deadlines and reliability requirements.

The current project is a runnable minimum transport: it can send text and files
between two devices using DART's own packet format, fragmentation, ACKs,
retransmission, sliding window, RTT estimation, and basic congestion control.

The runnable sender and receiver now use the DART v2 binary packet format. A
message is split into UDP-sized fragments, each fragment is acknowledged and
retried when required, and the receiver reassembles the original message before
delivering it.

This is still a deliberately simple prototype, but it can keep several packets
in flight and adjusts that number after ACKs and packet loss. DART does not yet
provide production-grade congestion control, flow control, security, handshakes,
or deadline queue scheduling.

The proposed v2 protocol and its delivery semantics are specified in
[`docs/protocol-v2.md`](docs/protocol-v2.md). Features described there may still
be future targets unless the README says they are implemented.

## Run the Demo

Start the receiver:

```bash
python receiver.py
```

Send a partially reliable message from another terminal:

```bash
python sender.py "hello" --mode partial --deadline-ms 1500
```

The available modes are `unreliable`, `partial`, and `reliable`. Run either
script with `--help` to see its simulation and timing options.

## Send A File

Start the receiver:

```bash
python receiver.py --output-dir received
```

Send any file from another terminal:

```bash
python sender.py --file example.pdf --mode reliable
```

The received file is saved as `received/example.pdf`. Binary files are supported;
the file does not need to contain text.

## Send Between Two Devices

Both devices must be on a network where UDP port `9999` is reachable. On the
receiving device, listen on all interfaces:

```bash
python receiver.py --host 0.0.0.0 --port 9999 --output-dir received
```

On the sending device, replace the address with the receiver's IP:

```bash
python sender.py --host 192.168.1.50 --port 9999 --file example.pdf --mode reliable
```

Allow UDP port `9999` through the receiving device's firewall if necessary.

To demonstrate fragment retransmission, start the receiver with:

```bash
python receiver.py --drop-first
```

Then send a message larger than one packet:

```bash
python sender.py "A long message..." --mode reliable --window-size 4
```

The sender reports the number of fragments and retries. The receiver delivers
the text only after every fragment has arrived.

## Implemented Milestone

- Binary `DATA` and `ACK` packets.
- 64-bit connection and packet numbers.
- Messages split into payloads of at most 1146 bytes.
- Out-of-order reassembly and duplicate suppression.
- A sliding window with a configurable maximum size.
- Minimal AIMD congestion control: additive growth after ACKs and window halving
  after a timeout.
- Selective ACK bitmaps that can acknowledge up to 65 packet numbers.
- Per-fragment timeout and retransmission.
- Measured RTT and an automatically adjusted retransmission timeout.
- Timeout backoff after packet loss.
- Unreliable, partial, and reliable sending modes.
- Sender-side deadline abandonment based on the estimated time needed for all
  remaining fragments.
- Simulated data loss, ACK loss, delay, and first-send loss.
- Text and binary file transfer applications.

## Not Implemented Yet

- Handshake and connection state machine.
- Receiver-side deadline expiration.
- Deadline-aware queue scheduling.
- Receiver-advertised flow control.
- Packet pacing or production-grade congestion fairness.
- Encryption or authentication.

This is an educational prototype. Do not expose it directly to the public
internet because packets and transferred files are not encrypted or
authenticated.

## Run Tests

```bash
python -m unittest discover -s tests -v
```
