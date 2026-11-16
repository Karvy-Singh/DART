# DART

DART (Deadline-Aware Reliable Transport) is an educational, message-oriented
transport protocol built over UDP. Its research goal is to make scheduling and
retransmission decisions using message deadlines and reliability requirements.

The current project is a runnable minimum transport: it can send text and files
between two devices using DART's own packet format, fragmentation, ACKs,
retransmission, sliding window, RTT estimation, and basic congestion control.

The runnable sender and receiver now use the DART v3 binary packet format. A
message is split into UDP-sized fragments, each fragment is acknowledged and
retried when required, and the receiver reassembles the original message before
delivering it.

This is still a deliberately simple prototype, but it now includes connection
handshakes, deadline scheduling, receiver expiration, receiver-advertised flow
limits, packet pacing, and reproducible network impairment controls. It does not
provide production-grade security or congestion fairness.

The proposed v3 protocol and its delivery semantics are specified in
[`docs/protocol-v3.md`](docs/protocol-v3.md). Features described there may still
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

## Send A Scheduled Batch

`examples/batch.json` contains reliable and partial messages with different
deadlines and priorities:

```bash
python sender.py --batch examples/batch.json
```

The sender uses earliest-deadline-first ordering. Messages that expire while
waiting are abandoned. A batch entry has either `text` or `file`, plus `mode`,
`priority`, and `deadline_ms` for partial messages.

```json
{
  "text": "urgent update",
  "mode": "partial",
  "deadline_ms": 300,
  "priority": 10
}
```

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
- Messages split into payloads of at most 1138 bytes.
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
- `HELLO`, `HELLO_ACK`, and `CLOSE` connection state machine.
- Earliest-deadline-first scheduling for JSON message batches.
- Receiver-side expiration of stale partial messages.
- Receiver-advertised maximum in-flight window.
- RTT-based packet pacing.
- Seeded loss, ACK loss, delay, jitter, and first-send-loss simulation.

## Not Implemented Yet

- Encryption or authentication.
- Dynamic flow-window updates after the handshake.
- Production-grade congestion control and fairness.
- Clock-offset negotiation; physical devices should synchronize their clocks
  for accurate receiver-side deadline decisions.

This is an educational prototype. Do not expose it directly to the public
internet because packets and transferred files are not encrypted or
authenticated.

## Run Tests

```bash
python -m unittest discover -s tests -v
```

Network impairment example:

```bash
python receiver.py --loss 0.05 --ack-loss 0.02 --delay-ms 40 --jitter-ms 10 --seed 7
```
