"""udp_ping.py - UDP ping client.

How it works:
  1. Put a sequence number and a send timestamp in each packet.
  2. Send it to the echo server.
  3. Wait up to --timeout seconds for the echo.
  4. RTT = time reply arrived - time request was sent.
  5. No reply in time -> count it as lost.

Key lesson: UDP gives you NO delivery guarantee. Loss, duplicates and
reordering are all possible. That is why we check the sequence number in
the reply: a late reply to probe 3 must not be counted as the reply to probe 4.

Run:  python3 udp_ping.py 127.0.0.1 --port 9000 -c 10
"""
import argparse
import socket
import struct
import time

from stats import summarize

# Packet layout: 4-byte sequence number + 8-byte float timestamp, network
# byte order ("!"). Then optional padding bytes to reach --size.
HDR = struct.Struct("!Id")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("host")
    ap.add_argument("--port", type=int, default=9000)
    ap.add_argument("-c", "--count", type=int, default=10)
    ap.add_argument("-i", "--interval", type=float, default=0.2)
    ap.add_argument("-W", "--timeout", type=float, default=1.0)
    ap.add_argument("-s", "--size", type=int, default=32, help="payload bytes")
    a = ap.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rtts = []

    for seq in range(a.count):
        # perf_counter is a monotonic, high-resolution clock. Never use
        # time.time() for intervals: it can jump if the system clock changes.
        t0 = time.perf_counter()
        pkt = HDR.pack(seq, t0)
        pkt += b"x" * max(0, a.size - len(pkt))
        sock.sendto(pkt, (a.host, a.port))

        deadline = t0 + a.timeout
        got = False
        while True:
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                break
            sock.settimeout(remaining)
            try:
                data, _ = sock.recvfrom(65535)
            except socket.timeout:
                break
            rseq, _ = HDR.unpack_from(data)
            if rseq != seq:
                # A stale reply from an earlier probe that timed out. Ignore.
                continue
            rtt = (time.perf_counter() - t0) * 1000
            rtts.append(rtt)
            print(f"{len(data)} bytes from {a.host}: seq={seq} rtt={rtt:.3f} ms")
            got = True
            break
        if not got:
            print(f"seq={seq} timeout")

        # Wait the rest of the interval before the next probe.
        time.sleep(max(0, a.interval - (time.perf_counter() - t0)))

    sock.close()
    summarize(f"{a.host}:{a.port} (udp)", a.count, rtts)


if __name__ == "__main__":
    main()
