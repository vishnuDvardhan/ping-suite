#!/usr/bin/env bash
# experiment.sh - the "20% packet loss" experiment from the resume line.
# Run as root on a Linux machine with netem available.
#   sudo ./experiment.sh
set -u
cd "$(dirname "$0")"
N=200

python3 udp_server.py --port 9000 >/dev/null 2>&1 & U=$!
python3 tcp_server.py --port 9001 --idle 60 >/dev/null 2>&1 & T=$!
trap 'kill $U $T 2>/dev/null; ./netem.sh off lo >/dev/null' EXIT
sleep 0.5

for rule in "loss 0%" "loss 10.6%" "loss 20%" "delay 20ms 5ms" "delay 20ms 5ms loss 10.6%"; do
  echo "================ netem: $rule ================"
  ./netem.sh on lo "$rule" >/dev/null
  echo "-- UDP";        python3 udp_ping.py 127.0.0.1 -c $N -i 0.01 -W 0.5 | tail -3
  echo "-- ICMP";       python3 icmp_ping.py 127.0.0.1 -c $N -i 0.01 -W 0.5 | tail -3
  echo "-- TCP echo";   python3 tcp_ping.py 127.0.0.1 --mode echo -c $N -i 0.01 -W 5 | tail -3
done
