"""udp_server.py - UDP echo server.

UDP has no connections. The server just waits for a datagram and sends the
same bytes back to whoever sent it. One socket serves every client, so no
threads are needed here.

Optional --drop lets you fake packet loss in software (useful on machines
without `tc`). Real loss testing should use tc netem (see netem.sh).

Run:  python3 udp_server.py --port 9000 [--drop 0.2]
"""
import argparse
import random
import socket


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=9000)
    ap.add_argument("--drop", type=float, default=0.0,
                    help="fraction of packets to ignore (fake loss)")
    a = ap.parse_args()

    # AF_INET = IPv4, SOCK_DGRAM = UDP.
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    # Let us restart the server right away on the same port.
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((a.host, a.port))
    print(f"UDP echo server on {a.host}:{a.port} (drop={a.drop})")

    while True:
        # recvfrom returns the data AND the sender's (ip, port).
        # 65535 is the max UDP payload size, so nothing gets cut off.
        data, addr = sock.recvfrom(65535)
        if random.random() < a.drop:
            continue  # pretend the packet was lost
        sock.sendto(data, addr)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
