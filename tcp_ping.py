"""tcp_ping.py - TCP ping client, two modes.

--mode connect  (default)
    Time how long connect() takes. connect() returns after the 3-way
    handshake: SYN -> SYN-ACK -> ACK. So this measures ~1 network RTT.
    It works against ANY open TCP port (e.g. a web server on 80/443) with
    no special server. "Host availability" = did the handshake succeed?
      - success           -> port open, host up
      - ConnectionRefused -> host up, port closed (it replied with RST)
      - timeout           -> host down, or a firewall silently drops SYNs

--mode echo
    Open one connection, then send length-prefixed messages to our
    tcp_server.py and time each echo. This measures application-level RTT
    on an existing connection.

Big lesson: TCP RETRANSMITS lost packets. Under packet loss, TCP pings
rarely "fail". Instead the RTT jumps by the retransmission timeout
(Linux minimum RTO = 200 ms; a lost SYN waits 1 s). Compare this with UDP,
where loss shows up directly as missing replies.

Run:  python3 tcp_ping.py 127.0.0.1 --port 9001 -c 10 [--mode echo]
"""
import argparse
import socket
import struct
import time

from stats import summarize

LEN = struct.Struct("!I")


def recv_exact(conn, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("server closed connection")
        buf += chunk
    return bytes(buf)


def ping_connect(a):
    rtts = []
    for seq in range(a.count):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(a.timeout)
        t0 = time.perf_counter()
        try:
            s.connect((a.host, a.port))
            rtt = (time.perf_counter() - t0) * 1000
            rtts.append(rtt)
            print(f"connected to {a.host}:{a.port}: seq={seq} time={rtt:.3f} ms")
        except socket.timeout:
            print(f"seq={seq} timeout (host down or SYN filtered)")
        except ConnectionRefusedError:
            print(f"seq={seq} refused (host up, port closed)")
        except OSError as e:
            print(f"seq={seq} error: {e}")
        finally:
            s.close()
        time.sleep(max(0, a.interval - (time.perf_counter() - t0)))
    return rtts


def ping_echo(a):
    rtts = []
    s = socket.create_connection((a.host, a.port), timeout=a.timeout)
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    payload = b"x" * a.size
    try:
        for seq in range(a.count):
            t0 = time.perf_counter()
            try:
                s.sendall(LEN.pack(len(payload)) + payload)
                (n,) = LEN.unpack(recv_exact(s, LEN.size))
                recv_exact(s, n)
                rtt = (time.perf_counter() - t0) * 1000
                rtts.append(rtt)
                print(f"echo from {a.host}:{a.port}: seq={seq} time={rtt:.3f} ms")
            except socket.timeout:
                # On a stream, a timeout leaves the stream in an unknown
                # state (the reply may still arrive later). Safest: stop.
                print(f"seq={seq} timeout - stream state unknown, stopping")
                break
            time.sleep(max(0, a.interval - (time.perf_counter() - t0)))
    finally:
        s.close()
    return rtts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("host")
    ap.add_argument("--port", type=int, default=9001)
    ap.add_argument("--mode", choices=["connect", "echo"], default="connect")
    ap.add_argument("-c", "--count", type=int, default=10)
    ap.add_argument("-i", "--interval", type=float, default=0.2)
    ap.add_argument("-W", "--timeout", type=float, default=2.0)
    ap.add_argument("-s", "--size", type=int, default=32)
    a = ap.parse_args()

    rtts = ping_connect(a) if a.mode == "connect" else ping_echo(a)
    summarize(f"{a.host}:{a.port} (tcp-{a.mode})", a.count, rtts)


if __name__ == "__main__":
    main()
